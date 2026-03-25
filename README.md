# spatial-inspector

국토지리정보원 수령 시설 Point SHP 자료를 전년도와 비교 검수하고 Word 보고서를 생성하는 Claude 기반 에이전트.

## 검수 단계
0. 폴더 전처리 — 연도별 파일 정규화, CRS 재투영(EPSG:5179), 추후분석 분리
1. 시계열 수량 비교 — 전년/금년 시설별 증감
2. 중복 레코드 탐지·제거 — fac_nm + fac_add + x_coord + y_coord 기준
3. 지오코딩 정확도 — 읍면동 경계 공간조인으로 좌표-주소 불일치 탐지
4. Word 보고서 자동 생성

## 설치
pip install -r requirements.txt

## 실행
# Claude API 사용 (대화형)
set ANTHROPIC_API_KEY=sk-ant-...
python agent.py

# API 없이 테스트 (dry run)
python agent.py -dry

## SHP 컬럼 규격
| 컬럼 | 설명 |
|------|------|
| fac_nm | 시설명 |
| fac_add | 주소 (지번주소) |
| x_coord | X좌표 |
| y_coord | Y좌표 |
좌표계: EPSG:5179 (Korea 2000 Unified CS)

## 요구사항
Python 3.10+, geopandas, anthropic, python-docx
