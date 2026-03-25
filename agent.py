"""Point SHP 검수 에이전트"""

import os
import sys
import json
import anthropic

# Windows 콘솔 인코딩 문제 방지
for _attr in ("stdout", "stderr", "stdin"):
    _s = getattr(sys, _attr)
    if _s and hasattr(_s, "encoding") and _s.encoding and _s.encoding.lower() not in ("utf-8", "utf8"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from tools.folder_prep import validate_and_prepare
from tools.count_compare import compare_facility_counts
from tools.duplicate import find_and_remove_duplicates
from tools.geocode_check import check_geocoding_accuracy
from tools.report import generate_word_report

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """당신은 국토지리정보원 시설 point SHP 자료 검수 전문 AI입니다.

검수는 반드시 아래 순서로 진행합니다:
0. 입력 데이터 전처리 (폴더 유효성 검사, 좌표계 확인/재투영)
1. 시계열 수량 비교 (전년 vs 금년 폴더)
2. 중복 레코드 탐지 및 제거 (금년 자료 기준)
3. 지오코딩 정확도 확인 (읍면동 경계 공간조인)
4. Word 보고서 생성

사용자가 폴더 경로와 읍면동 SHP를 알려주면 순서대로 도구를 호출하여 검수를 완료하세요.
결과는 항상 한국어로 요약하고, 최종적으로 Word 보고서를 생성합니다.

컬럼 규격:
- 시설명: fac_nm
- 주소: fac_add
- X좌표: x_coord
- Y좌표: y_coord
- 좌표계: EPSG:5179
"""

TOOLS = [
    {
        "name": "validate_and_prepare",
        "description": "검수 시작 전 0단계: 전년/금년 폴더 구조를 정규화하고 시설 파일을 정렬합니다. 접두사 제거·유사 이름 매핑·좌표계 재투영을 수행하며, 이후 도구들은 반환된 prepared 경로를 사용합니다. 반드시 다른 도구보다 먼저 호출하세요.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prev_folder": {"type": "string", "description": "전년도 SHP 파일 폴더 경로"},
                "curr_folder": {"type": "string", "description": "금년도 SHP 파일 폴더 경로"},
                "emd_shp": {"type": "string", "description": "읍면동 경계 SHP 파일 경로 (전처리에는 사용 안 하지만 이후 단계를 위해 기록)"},
                "work_dir": {"type": "string", "description": "전처리 결과 저장 폴더 (기본값: prev_folder 상위/_prepared)"},
                "fix_crs": {"type": "boolean", "description": "true: EPSG:5179 아닌 SHP 자동 재투영 (기본값 true)", "default": True},
            },
            "required": ["prev_folder", "curr_folder", "emd_shp"],
        },
    },
    {
        "name": "compare_facility_counts",
        "description": "전년도/금년도 SHP 폴더를 비교하여 시설별 수량 증감을 분석합니다. 파일명이 시설 종류입니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prev_folder": {"type": "string", "description": "전년도 SHP 파일 폴더 경로"},
                "curr_folder": {"type": "string", "description": "금년도 SHP 파일 폴더 경로"},
            },
            "required": ["prev_folder", "curr_folder"],
        },
    },
    {
        "name": "find_and_remove_duplicates",
        "description": "SHP 폴더 내 모든 파일에서 fac_nm+fac_add+x_coord+y_coord가 동일한 중복 레코드를 탐지합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "shp_folder": {"type": "string", "description": "검사할 SHP 파일 폴더 경로 (보통 금년도 폴더)"},
                "output_folder": {"type": "string", "description": "중복 제거 후 SHP 저장 폴더 (remove=true일 때 필요)"},
                "remove": {"type": "boolean", "description": "true: 중복 제거 후 output_folder에 저장, false: 탐지만", "default": False},
            },
            "required": ["shp_folder"],
        },
    },
    {
        "name": "check_geocoding_accuracy",
        "description": "point SHP를 읍면동 경계 SHP와 공간조인하여 fac_add의 읍면동명과 실제 위치를 비교합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "point_folder": {"type": "string", "description": "point SHP 파일 폴더 경로"},
                "emd_shp": {"type": "string", "description": "읍면동 경계 SHP 파일 경로"},
                "emd_name_col": {"type": "string", "description": "읍면동명 컬럼명 (auto: 자동감지)", "default": "auto"},
            },
            "required": ["point_folder", "emd_shp"],
        },
    },
    {
        "name": "generate_word_report",
        "description": "3단계 검수 결과를 종합하여 Word(.docx) 보고서를 생성합니다. 반드시 앞의 3개 도구 실행 후 호출하세요.",
        "input_schema": {
            "type": "object",
            "properties": {
                "output_path": {"type": "string", "description": "저장할 Word 파일 경로 (예: C:/output/검수보고서.docx)"},
                "prev_folder": {"type": "string", "description": "전년도 폴더 경로"},
                "curr_folder": {"type": "string", "description": "금년도 폴더 경로"},
                "emd_shp": {"type": "string", "description": "읍면동 경계 SHP 경로"},
            },
            "required": ["output_path", "curr_folder"],
        },
    },
]

# 중간 결과 저장소 (에이전트 세션 내 공유)
_results = {}


def execute_tool(name: str, inputs: dict) -> str:
    global _results

    try:
        if name == "validate_and_prepare":
            data = validate_and_prepare(
                inputs["prev_folder"],
                inputs["curr_folder"],
                inputs.get("work_dir"),
                inputs.get("fix_crs", True),
            )
            if not data.get("준비완료"):
                return json.dumps({"준비완료": False, "오류": data.get("오류")}, ensure_ascii=False)

            # prepared 경로를 _results에 저장 → 이후 도구들이 자동 사용
            _results["prev_folder"] = data["전년_prepared"]
            _results["curr_folder"] = data["금년_prepared"]
            _results["emd_shp"] = inputs["emd_shp"]

            s = data["요약"]
            summary = {
                "준비완료": True,
                "전년_prepared": data["전년_prepared"],
                "금년_prepared": data["금년_prepared"],
                "추후분석_폴더": data.get("추후분석_폴더"),
                "전년_원본파일수": s["전년_원본파일수"],
                "금년_원본파일수": s["금년_원본파일수"],
                "정확일치_시설수": s["정확일치_시설수"],
                "유사이름_매핑": s["이름변경목록"],
                "전년에만있는시설": s["전년에만있는시설"],
                "추후분석목록": s["추후분석목록"],
                "좌표계재투영수": len(s["좌표계재투영"]),
                "안내": "이후 도구는 전년_prepared / 금년_prepared 경로를 사용하세요.",
            }
            return json.dumps(summary, ensure_ascii=False, indent=2)

        elif name == "compare_facility_counts":
            data = compare_facility_counts(inputs["prev_folder"], inputs["curr_folder"])
            _results["count"] = data
            _results["prev_folder"] = inputs["prev_folder"]
            _results["curr_folder"] = inputs["curr_folder"]
            # 요약만 반환 (토큰 절약)
            s = data["summary"]
            return json.dumps({
                "완료": True,
                "요약": s,
                "시설별수량(상위10)": data["rows"][:10],
            }, ensure_ascii=False, indent=2)

        elif name == "find_and_remove_duplicates":
            data = find_and_remove_duplicates(
                inputs["shp_folder"],
                inputs.get("output_folder"),
                inputs.get("remove", False),
            )
            _results["duplicate"] = data
            # 상세 제거 후 요약 반환
            summary = {
                "완료": True,
                "총중복수": data["총중복수"],
                "검사파일수": data["검사파일수"],
                "시설별요약": [
                    {"시설명": r["시설명"], "중복수": r.get("중복수", 0)}
                    for r in data["시설별결과"]
                    if r.get("중복수", 0) > 0
                ],
            }
            return json.dumps(summary, ensure_ascii=False, indent=2)

        elif name == "check_geocoding_accuracy":
            data = check_geocoding_accuracy(
                inputs["point_folder"],
                inputs["emd_shp"],
                inputs.get("emd_name_col", "auto"),
            )
            _results["geocode"] = data
            _results["emd_shp"] = inputs["emd_shp"]
            summary = {
                "완료": True,
                "전체일치율": f"{data['전체일치율(%)']:.1f}%",
                "전체수량": data["전체수량"],
                "전체일치": data["전체일치"],
                "시설별요약": [
                    {
                        "시설명": r["시설명"],
                        "일치율": f"{r.get('일치율(%)', 0):.1f}%",
                        "불일치": r.get("불일치", 0),
                    }
                    for r in data["시설별결과"]
                ],
            }
            return json.dumps(summary, ensure_ascii=False, indent=2)

        elif name == "generate_word_report":
            # 저장된 중간 결과 사용
            count_data = _results.get("count")
            dup_data = _results.get("duplicate")
            geo_data = _results.get("geocode")

            if not all([count_data, dup_data, geo_data]):
                missing = []
                if not count_data: missing.append("수량비교")
                if not dup_data: missing.append("중복탐지")
                if not geo_data: missing.append("지오코딩")
                return json.dumps({"오류": f"먼저 실행 필요: {missing}"}, ensure_ascii=False)

            out = generate_word_report(
                output_path=inputs["output_path"],
                count_data=count_data,
                dup_data=dup_data,
                geo_data=geo_data,
                prev_folder=_results.get("prev_folder", inputs.get("prev_folder", "")),
                curr_folder=inputs["curr_folder"],
                emd_shp=_results.get("emd_shp", inputs.get("emd_shp", "")),
            )
            return json.dumps({"완료": True, "저장경로": out}, ensure_ascii=False)

        else:
            return json.dumps({"오류": f"알 수 없는 도구: {name}"}, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"오류": str(e)}, ensure_ascii=False)


def run_dry(prev_folder: str, curr_folder: str, emd_shp: str, output_path: str, work_dir: str = None) -> None:
    """
    API 호출 없이 0~4단계 도구를 순서대로 직접 실행하는 dry run 모드.
    토큰 소비 없이 전체 파이프라인 동작을 검증할 수 있습니다.
    """
    global _results
    _results = {}

    print("\n" + "=" * 60)
    print("  [DRY RUN] API 호출 없이 파이프라인 실행")
    print("=" * 60)

    steps = [
        ("0단계: 전처리", "validate_and_prepare", {
            "prev_folder": prev_folder,
            "curr_folder": curr_folder,
            "emd_shp": emd_shp,
            **({"work_dir": work_dir} if work_dir else {}),
            "fix_crs": True,
        }),
        ("1단계: 수량비교", "compare_facility_counts", None),   # _results에서 경로 자동 참조
        ("2단계: 중복탐지", "find_and_remove_duplicates", None),
        ("3단계: 지오코딩", "check_geocoding_accuracy", None),
        ("4단계: 보고서생성", "generate_word_report", {"output_path": output_path, "curr_folder": ""}),
    ]

    for label, tool_name, inputs in steps:
        print(f"\n  ── {label} ──")

        # 전처리 완료 후 경로 자동 세팅
        if inputs is None:
            curr_prep = _results.get("curr_folder", curr_folder)
            dedup_folder = curr_prep + "_dedup"
            if tool_name == "compare_facility_counts":
                inputs = {
                    "prev_folder": _results.get("prev_folder", prev_folder),
                    "curr_folder": curr_prep,
                }
            elif tool_name == "find_and_remove_duplicates":
                inputs = {
                    "shp_folder": curr_prep,
                    "output_folder": dedup_folder,
                    "remove": True,
                }
            elif tool_name == "check_geocoding_accuracy":
                inputs = {
                    "point_folder": dedup_folder,
                    "emd_shp": _results.get("emd_shp", emd_shp),
                    "emd_name_col": "auto",
                }
        elif tool_name == "generate_word_report":
            inputs["curr_folder"] = _results.get("curr_folder", curr_folder)

        print(f"  [입력] {json.dumps(inputs, ensure_ascii=False)}")
        result = execute_tool(tool_name, inputs)
        parsed = json.loads(result)

        if parsed.get("오류"):
            print(f"  [오류] {parsed['오류']}")
        else:
            print(f"  [완료]")
            # 핵심 결과만 출력
            for key in ("전년_prepared", "금년_prepared", "요약", "전체일치율", "총중복수", "저장경로"):
                if key in parsed:
                    print(f"    {key}: {parsed[key]}")

    print("\n" + "=" * 60)
    print("  [DRY RUN 완료] 보고서:", output_path)
    print("=" * 60)


def run_agent(user_message: str) -> None:
    global _results
    _results = {}  # 새 검수 시작 시 초기화

    messages = [{"role": "user", "content": user_message}]
    print(f"\n사용자: {user_message}")
    print("─" * 60)

    while True:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        for block in response.content:
            if block.type == "text" and block.text:
                print(f"\nClaude: {block.text}")

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"\n  [도구] {block.name}")
                    print(f"  [입력] {json.dumps(block.input, ensure_ascii=False)}")
                    result = execute_tool(block.name, block.input)
                    parsed = json.loads(result)
                    print(f"  [결과] {'완료' if parsed.get('완료') else parsed.get('오류', '처리됨')}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
        else:
            break


def main():
    dry_run = "--dry-run" in sys.argv or "-dry" in sys.argv

    print("=" * 60)
    print("  Point SHP 검수 에이전트", "[DRY RUN]" if dry_run else "")
    print("  종료: q")
    print("=" * 60)

    if dry_run:
        print("\n경로를 직접 입력하세요 (API 호출 없음):")
        prev   = input("  전년도 폴더: ").strip()
        curr   = input("  금년도 폴더: ").strip()
        emd    = input("  읍면동 SHP : ").strip()
        output = input("  보고서 경로: ").strip()
        run_dry(prev, curr, emd, output)
        return

    print("\n사용 예시:")
    print("  → '전년 C:/data/2023, 금년 C:/data/2024,")
    print("     읍면동 C:/data/emd.shp 검수하고")
    print("     C:/output/검수보고서.docx 로 저장해줘'")

    while True:
        user_input = input("\n질문: ").strip()
        if not user_input:
            continue
        if user_input.lower() in ("q", "quit", "exit"):
            print("종료합니다.")
            break
        run_agent(user_input)


if __name__ == "__main__":
    main()
