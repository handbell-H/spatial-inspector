"""2단계: 중복 레코드 탐지 및 제거"""

import os
import json
import geopandas as gpd
import pandas as pd

DUP_COLS = ["fac_nm", "fac_add", "x_coord", "y_coord"]


def _check_cols(gdf, path):
    """필수 컬럼 존재 여부 확인, 없는 컬럼 목록 반환"""
    missing = [c for c in DUP_COLS if c not in gdf.columns]
    return missing


def find_and_remove_duplicates(shp_folder: str, output_folder: str = None, remove: bool = False) -> dict:
    """
    폴더 내 모든 SHP 파일에서 fac_nm + fac_add + x_coord + y_coord가
    모두 동일한 중복 레코드를 탐지. remove=True이면 제거 후 output_folder에 저장.
    """
    if not os.path.isdir(shp_folder):
        raise FileNotFoundError(f"폴더를 찾을 수 없습니다: {shp_folder}")

    if remove and output_folder:
        os.makedirs(output_folder, exist_ok=True)

    facility_results = []
    total_dup = 0

    shp_files = [f for f in os.listdir(shp_folder) if f.lower().endswith(".shp")]

    for fname in sorted(shp_files):
        fac_name = os.path.splitext(fname)[0]
        path = os.path.join(shp_folder, fname)

        try:
            gdf = gpd.read_file(path)
        except Exception as e:
            facility_results.append({"시설명": fac_name, "오류": str(e)})
            continue

        missing = _check_cols(gdf, path)
        if missing:
            facility_results.append({
                "시설명": fac_name,
                "전체수량": len(gdf),
                "중복수": 0,
                "비고": f"컬럼 없음: {missing}",
                "중복레코드": [],
            })
            continue

        # 중복 탐지 (4개 컬럼 모두 동일)
        dup_mask = gdf.duplicated(subset=DUP_COLS, keep=False)
        dup_gdf = gdf[dup_mask].copy()

        # 중복 그룹별 샘플 (첫 번째 제외한 나머지 = 실제 제거 대상)
        remove_mask = gdf.duplicated(subset=DUP_COLS, keep="first")
        dup_count = remove_mask.sum()
        total_dup += dup_count

        # 중복 레코드 상세 (최대 20건) — numpy 타입 → Python 기본 타입 변환
        dup_detail = []
        if dup_count > 0:
            dup_rows = gdf[remove_mask][DUP_COLS].head(20)
            dup_detail = [
                {k: (v.item() if hasattr(v, "item") else v) for k, v in row.items()}
                for row in dup_rows.to_dict(orient="records")
            ]

        result = {
            "시설명": fac_name,
            "전체수량": len(gdf),
            "중복수": int(dup_count),
            "제거후수량": len(gdf) - int(dup_count),
            "중복레코드": dup_detail,
        }
        facility_results.append(result)

        # 중복 제거 후 저장
        if remove and output_folder and dup_count > 0:
            cleaned = gdf[~remove_mask].copy()
            out_path = os.path.join(output_folder, fname)
            cleaned.to_file(out_path, encoding="utf-8")
            result["저장경로"] = out_path
        elif remove and output_folder:
            # 중복 없어도 복사
            out_path = os.path.join(output_folder, fname)
            gdf.to_file(out_path, encoding="utf-8")

    return {
        "시설별결과": facility_results,
        "총중복수": int(total_dup),
        "검사파일수": len(shp_files),
    }
