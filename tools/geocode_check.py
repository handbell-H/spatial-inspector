"""3단계: 지오코딩 정확도 확인 (공간조인 기반)"""

import os
import re
import geopandas as gpd
import pandas as pd

# 읍면동 경계 SHP에서 자동 감지할 컬럼 후보
EMD_COL_CANDIDATES = ["EMD_NM", "ADM_NM", "읍면동명", "EMD_KOR_NM", "emd_nm", "adm_nm"]

# 읍면동 토큰 패턴: 한글 + 선택적숫자 + 읍/면/동 (+ 선택적 숫자가)
# 예) 호저면, 역삼동, 역삼1동, 효자동3가, 명동1가
_EMD_TOKEN_RE = re.compile(r"^[가-힣]+\d*(?:읍|면|동)(?:\d+가)?$")

# 시도·시군구 접미사 — 읍면동과 혼동될 수 있는 상위 행정구역 제외용
_UPPER_SUFFIXES = ("특별시", "광역시", "특별자치시", "특별자치도", "도", "시", "군", "구")


def _extract_emd_from_address(address: str) -> str | None:
    """
    주소를 공백으로 분리한 뒤 토큰 단위로 읍면동을 찾는다.
    도로명·번지(숫자·영문·특수문자 포함 토큰)는 자동 제외된다.

    예) "강원특별자치도 원주시 호저면 운동들2길 21-33" → "호저면"
        "서울특별시 강남구 역삼1동 123-45"            → "역삼1동"
        "전북 전주시 완산구 효자동3가"                 → "효자동3가"
        "경기도 수원시 팔달구 매산로 1번길 5"          → None (읍면동 없는 도로명주소)
    """
    if not isinstance(address, str):
        return None
    for token in address.split():
        if _EMD_TOKEN_RE.match(token) and not any(token.endswith(s) for s in _UPPER_SUFFIXES):
            return token
    return None


def _detect_emd_col(gdf: gpd.GeoDataFrame) -> str | None:
    """읍면동명 컬럼 자동 감지"""
    for cand in EMD_COL_CANDIDATES:
        if cand in gdf.columns:
            return cand
    # 이름에 'nm' 또는 '명' 포함되는 컬럼 검색
    for col in gdf.columns:
        if "nm" in col.lower() or "명" in col:
            return col
    return None


def check_geocoding_accuracy(point_folder: str, emd_shp: str, emd_name_col: str = "auto") -> dict:
    """
    point SHP의 좌표를 읍면동 경계 SHP와 공간조인하여
    fac_add의 읍면동명과 실제 위치의 읍면동명을 비교.

    - 일치: 지오코딩 정확
    - 불일치: 지오코딩 오류 의심
    - 조인실패: 경계 밖(바다/국외 등)
    """
    if not os.path.isdir(point_folder):
        raise FileNotFoundError(f"폴더를 찾을 수 없습니다: {point_folder}")
    if not os.path.isfile(emd_shp):
        raise FileNotFoundError(f"읍면동 SHP를 찾을 수 없습니다: {emd_shp}")

    # 읍면동 경계 로드
    emd_gdf = gpd.read_file(emd_shp)

    # 읍면동명 컬럼 확인
    if emd_name_col == "auto":
        emd_name_col = _detect_emd_col(emd_gdf)
        if not emd_name_col:
            raise ValueError(
                f"읍면동명 컬럼을 자동 감지하지 못했습니다. "
                f"컬럼 목록: {emd_gdf.columns.tolist()}"
            )

    # CRS 통일 (EPSG:5179)
    if emd_gdf.crs is None or emd_gdf.crs.to_epsg() != 5179:
        emd_gdf = emd_gdf.to_crs(epsg=5179)

    facility_results = []
    shp_files = [f for f in os.listdir(point_folder) if f.lower().endswith(".shp")]

    for fname in sorted(shp_files):
        fac_name = os.path.splitext(fname)[0]
        path = os.path.join(point_folder, fname)

        try:
            gdf = gpd.read_file(path)
        except Exception as e:
            facility_results.append({"시설명": fac_name, "오류": str(e)})
            continue

        if "fac_add" not in gdf.columns:
            facility_results.append({
                "시설명": fac_name,
                "비고": "fac_add 컬럼 없음",
            })
            continue

        # CRS 통일
        if gdf.crs is None or gdf.crs.to_epsg() != 5179:
            gdf = gdf.to_crs(epsg=5179)

        total = len(gdf)

        # 공간조인: point → 읍면동
        joined = gpd.sjoin(
            gdf[["fac_nm", "fac_add", "geometry"]],
            emd_gdf[[emd_name_col, "geometry"]],
            how="left",
            predicate="within",
        )

        # 주소에서 읍면동 추출
        joined["addr_emd"] = joined["fac_add"].apply(_extract_emd_from_address)
        joined["joined_emd"] = joined[emd_name_col]

        # 비교
        # NaN 처리: 조인 실패(경계 밖)
        joined_fail = joined["joined_emd"].isna()
        addr_fail = joined["addr_emd"].isna()

        match = (~joined_fail) & (~addr_fail) & (joined["addr_emd"] == joined["joined_emd"])
        mismatch = (~joined_fail) & (~addr_fail) & (joined["addr_emd"] != joined["joined_emd"])
        join_fail_count = joined_fail.sum()

        # 불일치 상세 (최대 20건)
        mismatch_detail = []
        if mismatch.sum() > 0:
            mis_rows = joined[mismatch][["fac_nm", "fac_add", "addr_emd", "joined_emd"]].head(20)
            mismatch_detail = mis_rows.rename(columns={
                "fac_nm": "시설명",
                "fac_add": "주소",
                "addr_emd": "주소상_읍면동",
                "joined_emd": "공간조인_읍면동",
            }).to_dict(orient="records")

        addr_fail_count = addr_fail.sum()
        match_rate = round(match.sum() / total * 100, 1) if total > 0 else 0.0

        facility_results.append({
            "시설명": fac_name,
            "전체수량": total,
            "일치": int(match.sum()),
            "불일치": int(mismatch.sum()),
            "조인실패(경계밖)": int(join_fail_count),
            "주소추출불가": int(addr_fail_count),
            "일치율(%)": match_rate,
            "불일치상세": mismatch_detail,
        })

    total_all = sum(r.get("전체수량", 0) for r in facility_results)
    total_match = sum(r.get("일치", 0) for r in facility_results)
    overall_rate = round(total_match / total_all * 100, 1) if total_all > 0 else 0.0

    return {
        "사용된_읍면동컬럼": emd_name_col,
        "시설별결과": facility_results,
        "전체일치율(%)": overall_rate,
        "전체수량": total_all,
        "전체일치": total_match,
    }
