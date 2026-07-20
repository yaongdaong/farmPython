class SMSRequest(BaseModel):
    phone_number: str
    item: str
    quantity: str

class SpringBootOrder(BaseModel):
    item: str # 판매 작물
    quantity_sold: int # 판매 수량 (통/kg)
    price_per_unit: int # 단가
    cost_per_unit: int # 원가 (순수익 계산용)
    
# --- 3단계: 고객 대상 입고 알림 문자 발송 (Mock) ---
@app.post("/farm/send-stock-sms")
def send_stock_sms(request: SMSRequest):
    print(f"\n==================================================")
    print(f"[REAL-TIME SMS SERVER] B2C 입고 알림 발송")
    print(f"수신인: {request.phone_number}")
    print(f"내용: [행복농장] 갓 수확한 신선한 {request.item}가 오늘 {request.quantity} 입고되었습니다! 한정 수량이니 쇼핑몰에서 서둘러 선점하세요!")
    print(f"==================================================\n")
    return {"status": "문자 발송 완료","receiver":request.phone_number}

# --- 3단계: 쇼핑몰 판매 데이터 수집 엔드포인트 (Spring Boot에서 호출용) ---
@app.post("/farm/shop-order")
def receive_order(order: SpringBootOrder):
    order_data = order.model_dump()
    order_data["total_revenue"] = order.quantity_sold * order.price_per_unit
    order_data["total_cost"]  = order.quantity_sold * order.cost_per_unit
    order_data["net_profit"] = order_data["total_revenue"] - order_data["total_cost"]
    order_data["date"] = datetime.now().strftime("%Y-%m-%d")

    result = sales_collection.insert_one(order_data)
    return {"status": "스프링부트 주문 데이터 동기화 성공", "sales_id": str(result.inserted_id)}

# --- 4단계: AI 엑셀 장부 자동 작성 (RPA 기술 탑재) ---
# 업그레이드: 온라인 + 오프라인 합산 및 지출 비용(농약값 등) 차감 장부 생성
@app.get("/farm/generate-excel")
def generate_excel():
    # DB에서 판매 데이터 긁어오기
    sales_docs = list(sales_collection.find())

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "2026 통합 정산 보고서"

    # 1. 엑셀 헤더 설정 (구분 필드 추가하여 온/오프라인 구별)
    headers = ["날짜", "유형", "품목", "세부 분류", "금액", "거래처/비고"]
    ws.append(headers)

    # 헤더 스타일링 (가독성 향상)
    header_font = Font(bole=True, color="FFFFFF")
    header_fill = PatternFill(statr_color="4F81BD", end_color="4F81BD", fill_type="solid")
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(hosizontal="center")

    total_revenue = 0  # 총수입 합계 (온라인 + 오프라인 수입 항목들)
    total_expense = 0  # 총지출 합계 (농약비, 비료비, 노동비 등)
    total_quantity = 0 # 총판매량 (통/kg)

    # 2. [온라인 데이터 수집] 스프링부트 쇼핑몰 판매 레코드 확보
    online_sales = list(sales_collection.find())
    for sale in online_sales:
        ws.append([
            sale.get("date", "-"),
            "수입",
            sale.get("item", "-"),
            "판매수익(온라인)",
            sale.get("total_revenue", 0),
            "쇼핑몰 결제완료"
        ])
        total_revenue += sale.get("total_revenue",0)
        total_quantity += sale.get("quantity_sold",0)

    # 3. [오프라인 데이터 수집] 메모 분석 로그에서 판매 내역 확보
    # (앞서 산딸기 메모처럼 AI가 파싱해서 logs 창고에 넣은 데이터 중 실제 판매분)
    farm_ledgers = list(logs_collection.find({"type": {"$in":["수입","지출"]}}))

    for ledger in farm_ledgers:
        l_type = ledger.get("type")          # 수입 또는 지출
        l_item = ledger.get("item", "공통")   # 품목 (산딸기, 블루베리 등)
        l_category = ledger.get("category")  # 세부 분류 (농약비, 노동비, 판매수익 등)
        l_amount = ledger.get("amount", 0)   # 금액
        l_memo = ledger.get("memo", "-")     # 내용 및 거래처
        l_date = ledger.get("date", "-")     # 일자

        ws.append([l_date, l_type, l_item, l_category, l_amount, l_memo])

        # 유형별 금액 누적
        if l_type == "수입":
            total_revenue += l_amount
            if "판매" in l_category: # 직거래 판매수익인 경우 수량 추정치 누적 가능 (기획에 따라 확장)
                total_quantity += ledger.get("quantity",0)
            elif l_type == "지출":
                total_expense += l_amount

    # 4. [최종 회계 정산 및 요약] 매출 - 지출 = 순수익 계산
    net_profit = total_revenue - total_expense

    ws.append([]) # 가독성을 위한 빈 줄
    ws.append(["=== 2026년 농장 경영 실적 최종 요약 ==="])
    ws.append(["총 출하/판매량", f"{total_quantity} 개(통/kg)"])
    ws.append(["총 수입 금액 (매출+보조금 등)", f"{total_revenue} 원"])
    ws.append(["총 지출 비용 (농약/비료/인건비 등)", f"-{total_expense} 원"])
    ws.append(["최종 순수익 (Net Profit)", f"{net_profit} 원"])

    # 요약 정보 스타일 서식 (RPA 시각화)
    summary_start_row = ws.max_row - 4
    for r in range(summary_start_row, ws.max_row +1):
        ws.cell(row=r, column=1).font = Font(bold=True)

    # 최종 순수익 행 빨갛게 강조하여 돈 흐름 눈에 띄게 만들기
    net_profit_cell = ws.cell(row=ws.max_row, column=2)
    net_profit_cell.font = Font(bold=True, color="FF0000", size=12)

    file_name = "Detailed_Farm_Financial_Report.xlsx"
    wb.save(file_name)

    return {
        "satatus": "입출금 세부 서식 반영 통합 장부 생성 성공",
        "file_path": os.path.abspath(file_name),
        "financial_summary": {
            "total_revenue": total_revenue,
            "total_expense": total_expense,
            "net_profit": net_profit
        }
    }

# --- 5단계: 엑셀 기반 AI 보고서 및 PPT 자동화 스크립트 가동 ---
@app.get("/farm/generate-report-ppt")
def generate_report_ppt():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY가 설정되지 않았습니다.")
    
    # 1. DB(MongoDB)에서 이번 조회 기간의 입출금 데이터 및 쇼핑몰 판매 데이터 총집계
    # 실제 환경에서는 쿼리 파라미터로 start_date, end_date를 받아 대시보드 화면과 동기화합니다.
    sales_docs = list(sales_collection.find())
    farm_ledgers = list(logs_collection.find({"type": {"$in": ["수입", "지출"]}}))
    
    # 대시보드 항목별 변수 초기화 (화면 UI와 1:1 매핑)
    dashboard_data = {
        "총수입": 0, "총지출": 0, "총합계_순수익": 0,
        "판매수익": 0, "가공품판매수익": 0, "농업부산물수익": 0, "농기계대여수입": 0,
        "정부보조금": 0, "임대료수익": 0, "수수료수익": 0, "이자수익": 0, "회비수입": 0, "유형자산처분이익": 0, "잡이익": 0, "수입_기타": 0,
        "농약비": 0, "비료비": 0, "노동비": 0, "종자_종묘비": 0, "기타재료비": 0, "중간재비": 0,
        "위탁영농비": 0, "수도광열비": 0, "임차료": 0, "수리_유지비": 0, "농구_영농시설_상각비": 0, "기타비용": 0
    }

    # 온라인 쇼핑몰 판매수익 먼저 합산
    for sale in sales_docs:
        dashboard_data["판매수익"] += sale.get("total_revenue", 0)
        dashboard_data["총수입"] += sale.get("total_revenue", 0)

    # 오프라인 영농 장부 데이터 분류 매핑
    for ledger in farm_ledgers:
        l_type = ledger.get("type")
        l_category = ledger.get("category")
        l_amount = ledger.get("amount", 0)
        
        # UI 세부 분류 명칭에 맞게 딕셔너리 매칭 매핑
        if l_category in dashboard_data:
            dashboard_data[l_category] += l_amount
        else:
            if l_type == "수입": dashboard_data["수입_기타"] += l_amount
            else: dashboard_data["기타비용"] += l_amount
            
        if l_type == "수입": dashboard_data["총수입"] += l_amount
        elif l_type == "지출": dashboard_data["총지출"] += l_amount

    dashboard_data["총합계_순수익"] = dashboard_data["총수입"] - dashboard_data["총지출"]

    # 2. 대시보드 팩트 데이터를 기반으로 Gemini에게 기업용 PPT 뼈대 및 요약 보고서 초안 요청
    client_gemini = genai.Client(api_key=api_key)
    
    prompt = f"""
    당신은 농업 전문 경영 컨설턴트이자 최고재무책임자(CFO) AI입니다.
    제공된 [입출금 소득분석 대시보드 데이터]를 날카롭게 분석하여 농장주에게 전송할 주간 경영 보고서 텍스트와 
    발표 및 브리핑용 PPT 슬라이드 기획안(총 5장 구성, 슬라이드별 제목/핵심 키워드/시각화 제안 포함)을 작성해 주세요.
    특히 매출 대비 농약비나 비료비 등 어떤 비용 항목이 과다 지출되었는지 짚어주고 순수익을 극대화할 제언을 포함해야 합니다.

    [입출금 소득분석 대시보드 데이터]
    {json.dumps(dashboard_data, ensure_ascii=False, indent=2)}

    반드시 마크다운 기호 없이 깔끔한 텍스트 리포트 형태로 출력하세요.
    """

    try:
        response = client_gemini.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        # 💡 백엔드 확장 팁: 실무 환경에서는 이 단계에서 `python-pptx` 라이브러리를 가동해 
        # dashboard_data의 값들로 원형 차트나 막대 그래프를 슬라이드 파일(.pptx)에 직접 그려 농장주 이메일로 쏴줍니다.
        print("\n==================================================")
        print("[RPA 파워포인트 빌더] 대시보드 데이터를 기반으로 PPTX 파일 생성 완료")
        print("==================================================\n")

        return {
            "status": "대시보드 기반 엑셀/PPT 통합 분석 성공",
            "dashboard_snapshot": {
                "total_revenue": dashboard_data["총수입"],
                "total_expense": dashboard_data["총지출"],
                "net_profit": dashboard_data["총합계_순수익"]
            },
            "ai_executive_report": response.text.strip()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PPT 분석서 생성 실패: {str(e)}")
    
@app.get("/farm/test-price")
def get_test_price(item_name: str):
    global df_price
    try:
        # 1. 엑셀에서 확인한 'PDLT_NM' 컬럼으로 필터링
        target_column = "PDLT_NM"

        if target_column not in df_price.columns:
            return {
                "status": "error",
                "message": f"CSV 파일에 '{target_column}' 컬럼이 업습니다. 실제 컬럼: {df_price.columns.tolist()}"
            }
        
        # 사용자가 '토마토'를 선택했을 때 ' 방울토마토'도 검색할 수 있도록 str.contains를 사용합니다.
        filtered_df = df_price[df_price[target_column].str.contains(item_name, na=False)] 

        # 데이터가 너무 많으면 브라우저가 뱉으므로 최근 100개나 일자별 평균 등으로 정제하면 좋지만, 
        # 우선 상위 200개만 샘플링해서 차트가 뜨는지 확인합니다.
        sample_df = filtered_df.head(200)

        chart_data = []
        for _, row in sample_df.iterrows():
            # 날짜 형식 변환 (20250502 -> "2025-05-02")
            raw_date = str(row.get("PRCE_REG",""))
            formatted_Date = raw_date
            if len(raw_date) == 8:
                formatted_date = f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}"

            # 가격 추출 (PDLT_PRC)
            price_val = 0
            try:
                price_val = int(row.get("PDLT_PRC",0))
            except:
                pass
            chart_data.append({
                "date": formatted_date,
                "wholesale_price":price_val,# 우선 도매/소매 모두에 할당하여 그래프 선이 나오게 만듭니다.
                "retail_price":price_val
            })

        # 프론트엔드 Recharts는 날짜 오름차순 정렬이어야 이쁘게 그려집니다.
        chart_data.sort(key=lambda x: x['date'])

        return {
            "status": "success",
            "data": chart_data
        }
    
    except Exception as e:
        print(f"에러 발생:{str(e)}")
        raise HTTPException(status_code=500,detail=str(e))

    
    if df_price is None:
        return {
            "status": "mock_mode",
            "message": "실제 CSV 파일이 없어 테스트용 가짜 데이터를 반환합니다.",
            "data": [
                {"date": "07-01", "wholesale_price": 9500, "retail_price": 14000},
                {"date": "07-02", "wholesale_price": 9800, "retail_price": 14500},
                {"date": "07-03", "wholesale_price": 10100, "retail_price": 15000}
            ]
        }
    
    try:
        # 공공데이터 CSV의 실제 컬럼명에 맞게 ['품목명'] 부분을 조율해야 할 수 있습니다.
        filtered_df = df_price[df_price["품목명"] == item_name]

        if filtered_df.empty:
            return {"status":"empty","message":f"'{item_name}' 품목 데이터가 없습니다."}
        
        result_data = []
        for _, row in filtered_df.iterrows():
            result_data.append({
                "date": str(row.get("일자","-")),
                "wholesale_price": int(row.get("도매가격",0)),
                "retail_price": int(row.get("소매가격",0))
            })

        return {"status": "success","item":item_name,"data":result_data}
    except Exception as se:
        raise HTTPException(status_code=500, detail=str(e))
# @app.get("/")
# def home():
#     return {"message": "농장 AI 자동화 서버가 가동 중입니다."}

# # [CREATE] 1. 데이터를 받아서 MongoDB에 저장하는 진짜 API (POST 방식)
# @app.post("/logs")
# def create_log(log: FarmLog):
#     # 받아온 데이터를 딕셔너리 형태로 변환
#     log_data = log.model_dump()

#     # MongoDB에 저장
#     result = logs_collection.insert_one(log_data)

#     return {"status":"성공", "inserted_id":str(result.inserted_id)}

# # [READ] 2. MongoDB에 저장된 모든 데이터를 꺼내오는 API (GET 방식)
# @app.get("/logs")
# def get_all_logs():
#     logs = []
#     # DB에서 전체 데이터를 조회(id 역순으로 최근 데이터부터)
#     for doc in logs_collection.find().sort("_id",-1):
#         logs.append({
#             "id": str(doc["_id"]),
#             "item": doc.get("item",doc.get("작물","-")),
#             "quantity":doc.get("quantity",doc.get("수확량","-")),
#             "memo":doc.get("memo",doc.get("메모","-"))
#         })
#     return {"total_count":len(logs),"data":logs}

# # [PARSING] 3. 폴더 안의 test.txt 파일을 읽어서 텍스트를 추출하는 API (GET 방식)
# @app.get("/read-txt")
# def read_txt():
#     file_path = "test.txt"

#     # 1. 파일이 진짜 존재하는지 체크
#     if not os.path.exists(file_path):
#         raise HTTPException(status_code=404, detail="test.txt 파일을 찾을 수 없습니다. 폴더 위치를 확인하세요.")
    
#     try:
#         # 2. 파일 열어서 텍스트 긁어오기 (한국어 깨짐 방지)
#         with open(file_path, "r", encoding="utf-8") as file:
#             content = file.read()

#         # 3. 읽어온 텍스트 반환하기
#         return {
#             "status": "txt 읽기 성공",
#             "file_name": file_path,
#             "extracted_text": content
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"파일을 읽는 중 오류 발생: {str(e)}")

# # [PARSING] 4. 폴더 안의 test.pdf 파일을 읽어서 텍스트를 추출하는 API (GET 방식)
# @app.get("/read-pdf")
# def read_pdf():
#     # 현재 main.py가 있는 폴더의 절대 경로를 구해 test.pdf의 경로를 완벽하게 고정
#     current_dir=os.path.dirname(os.path.abspath(__file__))
#     file_path = os.path.join(current_dir,"test.pdf")

#     # 1. 파일 존재 여부 체크 (💡 f접두사 추가)
#     if not os.path.exists(file_path):
#         raise HTTPException(status_code=404, detail=f"test.pdf 파일을 찾을 수 없습니다. 경로 확인: {file_path}")
    
#     try:
#         # 2. PDF 파일 열기
#         doc = fitz.open(file_path)
#         content = ""

#         # 3. PDF의 모든 페이지를 돌며 텍스트 추출
#         for page in doc:
#             content += page.get_text()

#         return {
#             "status": "pdf 읽기 성공",
#             "file_name": file_path,
#             "extracted_text": content
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"PDF를 읽는 중 오류 발생:{str(e)}")
    
# # 💡 [LLM + DB 연동] 5. 복잡한 문서를 정밀 JSON 데이터로 구조화하여 저장하는 마스터 API
# @app.get("/analyze-farm-doc")
# def analyze_farm_doc():
#     # 1. 앞에서 만든 절대 경로 방식으로 PDF 텍스트 추출
#     current_dir = os.path.dirname(os.path.abspath(__file__))
#     file_path = os.path.join(current_dir, "test.pdf")

#     if not os.path.exists(file_path):
#         raise HTTPException(status_code=404, detail="분석할 test.pdf 파일이 없습니다.")
    
#     try:
#         # 1. PDF 텍스트 추출
#         doc = fitz.open(file_path)
#         raw_text = ""
#         for page in doc:
#             raw_text += page.get_text()

#         # 2. Gemini API 키 세팅
#         api_key = os.environ.get("GEMINI_API_KEY")
#         if not api_key:
#             raise HTTPException(status_code=500, detail="서버 환경 변수에 GEMINI_API_KEY가 설정되지 않았습니다.")
#         client = genai.Client(api_key=api_key)

#       # 3. AI에게 내릴 강력한 B2C 마케팅용 프롬프트 정의 (가격 정보 필수화)
#         prompt = f"""
#         당신은 스마트팜 쇼핑몰의 전문 카피라이터이자 마케팅 AI입니다.
#         제공된 [원본 문서 내용]을 바탕으로 오늘 입고된 "작물 이름", "총 수량", 그리고 경락 단가나 총액을 기반으로 계산한 "소비자 기준 단위당 가격(예: 1kg당 가격 또는 1박스당 가격)"을 정확히 파악해 주세요.
        
#         이를 바탕으로 일반 소비자(B2C) 고객들이 가격 메리트를 느끼고 바로 구매하고 싶어지도록 상냥하고 친근한 톤앤매너로 입고 알림 문자 초안을 작성해 주세요.
#         문자 초안에는 반드시 "1kg에 OO원!" 또는 "1박스(Okg)에 OO원!" 같은 구체적인 가격 안내가 포함되어야 합니다.
#         정산, 수수료, 계좌번호 같은 딱딱한 B2B용 단어는 절대 포함하면 안 됩니다.

#         반드시 아래의 [JSON 반환 포맷] 규칙을 엄격히 준수하여 JSON 데이터만 반환하세요.
#         마크다운 기호(```json 등)는 절대 포함하지 말고 순수 JSON 문자열만 출력해야 합니다.

#         [원본 문서 내용]
#         {raw_text}

#         [JSON 반환 포맷]
#         {{
#             "item": "추출한 작물명 (예: 밤고구마, 토마토)",
#             "quantity": "입고된 총 수량 (예: 1,500kg, 20박스)",
#             "farm_name": "출하자 또는 농가명 (없으면 '미확인')",
#             "grade": "품질 등급 (예: 특상품, 특, 상)",
#             "harvest_date": "YYYY-MM-DD 형태로 작성",
#             "safe_shelf_life":5,
#             "sms_draft": "고객님! 오늘 당도 최고인 신선 [작물명]이 입고되었습니다! 밭에서 갓 수확해 싱싱한 [작물명]을 오늘만 '1kg에 OO원' (또는 '1박스에 OO원') 역대급 초특가로 모십니다 채널 링크 누르고 산지의 신선함을 만나보세요🛒"
#         }}
#         """

#         # 4. Gemini 최신 모델에게 요청 보내기
#         # response = client.models.generate_content(
#         #     model='gemini-2.5-flash',
#         #     contents=prompt
#         # )
#         model_instance = genai.GenerativeModel('gemini-2.5-flash')
#         response = model_instance.generate_content(prompt)

#         # 5. AI가 준 JSON 문자열을 파이썬 딕셔너리로 안전하게 변환
#         import json
#         clean_json_str = response.text.strip()
        
#         # 혹시 AI가 마크다운 블록을 씌웠을 경우 대비한 방어 코드
#         if clean_json_str.startswith("```"):
#             clean_json_str = clean_json_str.split("\n", 1)[1].rsplit("\n", 1)[0].strip()
#             if clean_json_str.startswith("json"):
#                 clean_json_str = clean_json_str[4:].strip()
                
#         parsed_data = json.loads(clean_json_str)

#         # 6. MongoDB에 완벽하게 구조화된 데이터 통째로 적재
#         db_data = {
#             "item": parsed_data.get("item", "미확인 작물"),
#             "quantity": parsed_data.get("quantity", "0"),
#             "farm_name": parsed_data.get("farm_name", "-"),
#             "grade": parsed_data.get("grade", "-"),
#             "harvest_date": parsed_data.get("harvest_date", datetime.now().strftime("%Y-%m-%d")),
#             "safe_shelf_life": parsed_data.get("safe_shelf_life", ""),
#             "memo": parsed_data.get("sms_draft", "")
#         }
#         inserted_result = logs_collection.insert_one(db_data)
#         # 프론트 반환용 오프셋 처리
#         db_data["_id"] = str(inserted_result.inserted_id)
#         # if "_id" in db_data:
#         #     db_data["_id"]=str(db_data["_id"])

#         return {
#             "status": "비정형 문서 정밀 구조화 및 DB 적재 성공",
#             # "saved_db_id": str(inserted_result.inserted_id),
#             "saved_db_id": db_data["_id"],
#             "parsed_data": db_data
#         }
#     except Exception as e:
#         # 💡 들여쓰기 라인을 깔끔하게 정렬했습니다.
#         raise HTTPException(status_code=500, detail=f"정밀 분석 중 오류 발생: {str(e)}")
#         # ai_result = response.text
#         # status_msg = "AI 분석 및 데이터베이스 저장 성공"

#     # except Exception as google_err:
#     #     # 구글 서버가 터지거나 키 오류가 나면 가짜 데이터로 우회해서 무조건 DB에 저장시킵니다. (진도 킵고잉용 방어코드) 
#     #     ai_result = f"[구글 서버 과부하로 인한 대피소 모드 가동]\n- 작물: 토마토\n- 수량: 200kg\n- 문자문자 메시지 초안: [행복농장] 서버 안정화 후 발송 예정 (에러로그: {str(google_err)})"
#     #     status_msg = "구글 서버 우회하여 임시 데이터베이스 저장"

#     #     # 5. MongoDB에 저장
#     # try:
#     #     db_data = {
#     #         "item": "토마토",
#     #         "quantity": "200kg",
#     #         "memo": ai_result
#     #     }

#     #     # MongoDB의 farm_db -> logs 창고에 저장
#     #     inserted_result = logs_collection.insert_one(db_data)

#     #     # 최종 성공 영수증 반환
#     #     return {
#     #         "status": "AI 분석 및 데이터베이스 저장 성공",
#     #         "saved_db_id": str(inserted_result.inserted_id),
#     #         "ai_analysis": ai_result
#     #     }
    
#     # except Exception as e:
#     #     raise HTTPException(status_code=500, detail=f"AI 분석 중 오류 발생: {str(e)}")
    
# # [SMS] 6. AI가 만든 초안을 가지고 실제 고객에게 문자 메시지를 전송하는 API (POST 방식)
# # 실무 환경을 가정한 가상 전송 모듈(Mock) 구현
# class FakeSMSClient:
#     @staticmethod
#     def send_message(phone_number: str, message: str) -> bool:
#         # 실제 환경이면 여기서 CoolSMS나 Twilio API를 호출하는 코드가 들어감
#         print(f"\n==================================================")
#         # 실제 2026년 현재 발송 시간 및 로그를 터미널에 출력
#         print(f"[REAL-TIME SMS SERVER] 2026-06-26 발송 요청 접수")
#         print(f"👉 수신인: {phone_number}")
#         print(f"👉 발송 내용:\n{message}")
#         print(f"==================================================\n")
#         return True
    
# # 외부에서 요청할 때 받을 전화번호 규격
# class SMSRequest(BaseModel):
#     phone_number: str
#     db_id: str # DB에서 문자 초안을 찾아오기 위한 영수증 ID

# @app.post("/send-sms")
# def send_sms(request: SMSRequest):
#     from bson import ObjectId # MongoDB ID 조회를 위한 부품

#     try:
#         # 1. 전달받은 db_id를 가지고 MongoDB에서 AI가 분석했던 원본 데이터 추적
#         doc = logs_collection.find_one({"_id":ObjectId(request.db_id)})

#         if not doc:
#             raise HTTPException(status_code=404,detail="해당 ID의 정산 로그를 DB에서 찾을 수 없습니다.")
        
#         # 2. DB에서 AI가 가공했던 문자 초안(memo 필드)을 꺼냄
#         ai_message = doc.get("memo","")

#         # 3. 가상 문자 발송 클라이언트를 가동해 발송을 찌름.
#         sms_client = FakeSMSClient()
#         success = sms_client.send_message(request.phone_number,ai_message)

#         if success:
#             return {
#                 "status": "문자 전송 완료",
#                 "receiver": request.phone_number,
#                 "sent_message": ai_message
#             }
#         else:
#             raise HTTPException(status_code=500, detail="문자 발송 서버 통신 실패")
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"문자 발송 처리 중 오류: {str(e)}")    
     
# # [KAKAO] 7.  AI 분석 데이터를 기반으로 카카오톡 알림톡을 발송하는 API (POST 방식)
# class KakaoAlimtalkClient:
#     @staticmethod
#     def send_alimtalk(phone_number: str, template_code: str, parameters: dict) -> bool:
#         # 실무 환경에서는 여기서 비즈뿌리오, 솔라피 등의 카카오 API 엔드포인트로 requests.post를 날립니다.
#         print(f"\n==================================================")
#         print(f"[KAKAO ALIMTALK SERVER] 알림톡 발송 요청 접수")
#         print(f"수신 번호: {phone_number}")
#         print(f"승인 템플릿 코드: {template_code}")
#         print(f"치환 데이터(AI 가공분):")
#         for key, value in parameters.items():
#             print(f" - {{{{{key}}}}}: {value}")

#         # 카카오톡 최종 도달 메시지 형태 가상 출력
#       # 💡 일반 소비자(B2C) 수신 화면으로 문구 개조 (가격/단가 강조)
#         print(f"\n[실제 카톡 수신 화면]")
#         print(f"▶ [행복농장] 갓 수확한 신선 농산물 입고 안내 🌿")
#         print(f"고객님, 기다리시던 신선한 '{parameters['item']}'가 오늘 농장에서 산지직송으로 입고되었습니다!")
#         print(f"산지 직거래로 거품을 쏙 빼고 오직 행복농장에서만 이 가격에 드립니다!")
#         print(f"\n{parameters['memo']}") # 👈 AI가 생성한 '가격이 포함된 문자 초안'이 여기에 쏙 들어갑니다.
#         print(f"\n지금 바로 아래 링크를 눌러 늦기 전에 선점하세요! 👉 쇼핑몰 바로가기")
#         print(f"==================================================\n")
#         return True
    
# # 카카오톡 요청용 데이터 규격
# # [버그 픽스] 프론트엔드가 실어 보내는 `is_emergency` 규격 확보
# class KakaoRequest(BaseModel):
#     phone_number: str
#     db_id: str
#     is_emergency: bool = False

# @app.post("/send-kakao")
# def send_kakao(request: KakaoRequest):
#     from bson import ObjectId

#     try:
#         # 1. MongoDB에서 AI가 저장한 정산 데이터 원본 확보
#         doc = logs_collection.find_one({"_id":ObjectId(request.db_id)})
#         if not doc:
#             raise HTTPException(status_code=404,detail="해당 ID의 로그를 DB에서 찾을 수 없습니다.")
        
#         # [신선도 연동] 유통기한이 2일 이하로 남았는지 백엔드에서 판별
#         # 여기서는 프론트에서 넘겨준 파라미터나 DB 기반으로 타임세일 모드로 전환 가능
#         is_emergency = request.is_emergency if hasattr(request, 'is_emergency') else False
#         item = doc.get("item","농산물")

#         # 긴급 세일 모드일 경우 AI 문구를 타임세일 톤으로 즉시 교체
#         # [버그 픽스] 긴급 세일 모드일 경우 위급 메시지로 치환
#         if request.is_emergency:
#             memo = f"[신선도 입박 30% 파격 타임세일] 오늘 소진 못 하면 밭으로 돌아갑니다! 갓 수확한 행복농장 {item} 한정수량 마감 임박! 지금 주문 시 내일 아침 식탁 도착"
#         else:
#             memo = doc.get("sms_draft","신선 농산물 입고 안내")

#         # 2. 카카오톡 승인 템플릿에 들어갈 핵심 데이터 바인딩
#         # (AI 분석으로 DB에 적재된 item과 quantity를 쏙 뽑아옵니다.)
#         # [버그 픽스] 위에서 동적으로 세팅한 'memo'가 변수에 바인딩되도록 전면 수정
#         kakao_variables = {
#             "item": doc.get("item","농산물"),
#             "quantity":doc.get("quantity","0kg"),
#             "memo": memo
#         }
        
#         # 3. 카카오톡 알림톡 모듈 가동
#         kakao_client = KakaoAlimtalkClient()
#         # 'tmpl_farm_01'은 카카오 측에 사전 심사 승인받은 가상의 템플릿 코드
#         success = kakao_client.send_alimtalk(
#             phone_number=request.phone_number,
#             template_code="tmpl_farm_01",
#             parameters=kakao_variables
#         )

#         if success:
#             return {
#                 "status":"카카오톡 알림톡 전송 완료",
#                 "template_code":"tmpl_farm_01",
#                 "substituted_data":kakao_variables
#             }
#         else:
#             raise HTTPException(status_code=500,detail="카카오톡 센터 통신 실패")
        
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"카카오톡 처리 중 오류:{str(e)}"),