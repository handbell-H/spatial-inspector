"""0단계: 입력 폴더 구조 정규화 및 시설 파일 정렬"""

import os
import re
import shutil
import difflib
import geopandas as gpd

TARGET_CRS = "EPSG:5179"
SHP_EXTS = {".shp", ".dbf", ".shx", ".prj", ".cpg", ".qpj", ".sbn", ".sbx"}

# 읍면동·행정경계 SHP 제외 키워드 (소문자 비교)
_BOUNDARY_KEYWORDS = {"읍면동", "행정", "경계", "행정구역", "emd", "시군구", "법정동", "행정동"}


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _is_boundary_file(stem: str) -> bool:
    """읍면동·행정경계 파일이면 True (시설 목록에서 제외)."""
    lower = stem.lower()
    return any(kw in lower for kw in _BOUNDARY_KEYWORDS)


def _normalize_stem(stem: str) -> str:
    """
    파일명 접두사 제거 → 순수 시설명 반환.
      2023_유치원   → 유치원
      05_유치원     → 유치원
      22_고속화철도 → 고속화철도
    """
    # 연도 접두사: 4자리 숫자 + _ (예: 2023_, 2024_)
    stem = re.sub(r"^\d{4}_", "", stem)
    # 번호 접두사: 1~2자리 숫자 + _ (예: 05_, 22_)
    stem = re.sub(r"^\d{1,2}_", "", stem)
    return stem.strip()


def _scan_shp(folder: str) -> dict:
    """
    폴더 및 1단계 하위폴더에서 시설 SHP 파일 탐색.
    - 읍면동·행정경계 파일은 자동 제외
    - 반환: {normalized_stem: 절대경로}
    """
    result = {}

    def _add(path: str):
        stem = os.path.splitext(os.path.basename(path))[0]
        if _is_boundary_file(stem):
            return
        norm = _normalize_stem(stem)
        if norm not in result:
            result[norm] = path

    # 직접 파일 먼저
    for entry in os.scandir(folder):
        if entry.is_file() and entry.name.lower().endswith(".shp"):
            _add(entry.path)
    # 하위폴더
    for entry in os.scandir(folder):
        if entry.is_dir():
            for sub in os.scandir(entry.path):
                if sub.is_file() and sub.name.lower().endswith(".shp"):
                    _add(sub.path)
    return result


def _copy_shp(src_shp: str, dst_dir: str, new_stem: str = None):
    """SHP 및 동반 파일을 dst_dir에 복사. new_stem 지정 시 파일명 변경."""
    src_dir = os.path.dirname(src_shp)
    src_stem = os.path.splitext(os.path.basename(src_shp))[0]
    out_stem = new_stem if new_stem else src_stem

    for fname in os.listdir(src_dir):
        fstem, fext = os.path.splitext(fname)
        if fstem == src_stem and fext.lower() in SHP_EXTS:
            shutil.copy2(
                os.path.join(src_dir, fname),
                os.path.join(dst_dir, out_stem + fext),
            )


def _reproject_if_needed(shp_path: str) -> bool:
    """EPSG:5179 아니면 재투영 후 덮어씀. 변환 여부 반환."""
    gdf = gpd.read_file(shp_path)
    if gdf.crs is None or gdf.crs.to_epsg() == 5179:
        return False
    gdf.to_crs(TARGET_CRS).to_file(shp_path, encoding="utf-8")
    return True


def _best_fuzzy(name: str, candidates: list, threshold: float = 0.65) -> str | None:
    """name과 가장 유사한 후보 반환. threshold 미만이면 None."""
    matches = difflib.get_close_matches(name, candidates, n=1, cutoff=threshold)
    return matches[0] if matches else None


# ── 메인 함수 ──────────────────────────────────────────────────────────────────

def validate_and_prepare(
    prev_folder: str,
    curr_folder: str,
    work_dir: str = None,
    fix_crs: bool = True,
) -> dict:
    """
    검수 전 폴더 전처리 6단계:
    1. 전년/금년 폴더 존재 확인
    2. 하위폴더 구조 → 단일 레벨로 통일 (work_dir 아래 복사)
    3. 동일/상이 시설 파일 분류
    4. 유사 이름 자동 매핑 후 전년 이름 기준으로 정규화
    5. 한쪽에만 있는 파일 → 적은 쪽 기준으로 정리
    6. 전년에 없는 금년 파일 → 추후분석 폴더

    반환값의 전년_prepared / 금년_prepared 경로를 이후 검수 도구에 사용하세요.
    """
    # ── 1. 폴더 존재 확인 ──────────────────────────────────────────────────────
    errors = []
    for label, folder in [("전년폴더", prev_folder), ("금년폴더", curr_folder)]:
        if not os.path.isdir(folder):
            errors.append(f"{label} 없음: {folder}")
    if errors:
        return {"준비완료": False, "오류": errors}

    # ── work_dir 초기화 ────────────────────────────────────────────────────────
    if work_dir is None:
        parent = os.path.dirname(os.path.abspath(prev_folder))
        work_dir = os.path.join(parent, "_prepared")

    prev_out = os.path.join(work_dir, "전년")
    curr_out = os.path.join(work_dir, "금년")
    future_out = os.path.join(work_dir, "추후분석")

    # 기존 내용 초기화 후 재생성
    for d in [prev_out, curr_out, future_out]:
        if os.path.isdir(d):
            shutil.rmtree(d)
        os.makedirs(d)

    # ── 2. SHP 파일 탐색 (직접 + 하위폴더 통일) ───────────────────────────────
    prev_shps = _scan_shp(prev_folder)   # {stem: path}
    curr_shps = _scan_shp(curr_folder)

    if not prev_shps and not curr_shps:
        return {"준비완료": False, "오류": ["두 폴더 모두 SHP 파일 없음"]}

    # ── 3. 정확 일치 / 상이 분류 ──────────────────────────────────────────────
    prev_stems = set(prev_shps)
    curr_stems = set(curr_shps)
    exact_common = prev_stems & curr_stems
    only_prev = prev_stems - curr_stems
    only_curr = curr_stems - prev_stems

    # ── 4. 유사 이름 매핑: only_curr → only_prev ──────────────────────────────
    # curr 기준으로 전년 이름에 맞춰 rename
    name_map: dict[str, str] = {}   # curr_stem → prev_stem(canonical)
    used_prev = set()

    for c_stem in sorted(only_curr):
        candidates = [p for p in only_prev if p not in used_prev]
        match = _best_fuzzy(c_stem, candidates)
        if match:
            name_map[c_stem] = match
            used_prev.add(match)

    # ── 5. 시설 정렬: 전년 기준 (매핑된 것 포함) ─────────────────────────────
    matched_prev_names = set(name_map.values())

    # 전년에만 있는 파일(매핑 안 됨) → 전년에는 포함 (수량비교에서 '삭제시설' 처리)
    only_prev_unmatched = only_prev - matched_prev_names

    # 금년에만 있고 매핑도 안 된 파일 → 추후분석
    future_stems = only_curr - set(name_map.keys())

    # ── 6. 파일 복사 ──────────────────────────────────────────────────────────
    reprojected = []

    # 전년: 비교 대상 + only_prev_unmatched 모두 복사
    for stem, path in prev_shps.items():
        _copy_shp(path, prev_out, stem)
        dst = os.path.join(prev_out, stem + ".shp")
        if fix_crs and _reproject_if_needed(dst):
            reprojected.append(f"전년/{stem}")

    # 금년: 비교 대상 복사 (유사 이름은 전년 이름으로 rename)
    for c_stem, path in curr_shps.items():
        if c_stem in exact_common:
            canonical = c_stem
        elif c_stem in name_map:
            canonical = name_map[c_stem]
        else:
            # 추후분석
            _copy_shp(path, future_out, c_stem)
            dst = os.path.join(future_out, c_stem + ".shp")
            if fix_crs and _reproject_if_needed(dst):
                reprojected.append(f"추후분석/{c_stem}")
            continue

        _copy_shp(path, curr_out, canonical)
        dst = os.path.join(curr_out, canonical + ".shp")
        if fix_crs and _reproject_if_needed(dst):
            reprojected.append(f"금년/{canonical}")

    renamed_list = [
        {"금년정규화명": c, "전년기준통일명": p} for c, p in name_map.items()
    ]

    return {
        "준비완료": True,
        "전년_prepared": prev_out,
        "금년_prepared": curr_out,
        "추후분석_폴더": future_out if future_stems else None,
        "요약": {
            "전년_원본파일수": len(prev_shps),
            "금년_원본파일수": len(curr_shps),
            "정확일치_시설수": len(exact_common),
            "유사이름_매핑수": len(name_map),
            "추후분석_시설수": len(future_stems),
            "전년에만있는시설": sorted(only_prev_unmatched),
            "이름변경목록": renamed_list,
            "추후분석목록": sorted(future_stems),
            "좌표계재투영": reprojected,
        },
    }
