"""1단계: 시계열 시설별 수량 비교"""

import os
import json
import geopandas as gpd


def compare_facility_counts(prev_folder: str, curr_folder: str) -> dict:
    """
    전년도/금년도 폴더의 SHP 파일을 비교하여 시설별 수량 증감 반환.
    파일명(확장자 제외)을 시설 종류로 사용.
    """
    def get_counts(folder):
        counts = {}
        if not os.path.isdir(folder):
            raise FileNotFoundError(f"폴더를 찾을 수 없습니다: {folder}")
        for fname in os.listdir(folder):
            if fname.lower().endswith(".shp"):
                name = os.path.splitext(fname)[0]
                try:
                    gdf = gpd.read_file(os.path.join(folder, fname))
                    counts[name] = len(gdf)
                except Exception as e:
                    counts[name] = f"읽기오류: {e}"
        return counts

    prev = get_counts(prev_folder)
    curr = get_counts(curr_folder)
    all_names = sorted(set(prev.keys()) | set(curr.keys()))

    rows = []
    for name in all_names:
        p = prev.get(name)
        c = curr.get(name)

        if isinstance(p, str) or isinstance(c, str):
            status = "오류"
            diff = None
        elif p is None:
            status = "신규시설"
            diff = c
        elif c is None:
            status = "추후 수령 후 분석"
            diff = -p
        else:
            diff = c - p
            status = "증가" if diff > 0 else "감소" if diff < 0 else "동일"

        rows.append({
            "시설명": name,
            "전년수량": p,
            "금년수량": c,
            "증감": diff,
            "상태": status,
        })

    summary = {
        "전년_시설종류수": len(prev),
        "금년_시설종류수": len(curr),
        "신규시설": [r["시설명"] for r in rows if r["상태"] == "신규시설"],
        "추후수령후분석": [r["시설명"] for r in rows if r["상태"] == "추후 수령 후 분석"],
        "전년_총수량": sum(v for v in prev.values() if isinstance(v, int)),
        "금년_총수량": sum(v for v in curr.values() if isinstance(v, int)),
    }
    summary["총증감"] = summary["금년_총수량"] - summary["전년_총수량"]

    return {"rows": rows, "summary": summary}
