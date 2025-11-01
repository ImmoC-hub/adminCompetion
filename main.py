# main.py

from fastapi import FastAPI, Request, Form, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette import status
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
import asyncio
from typing import Dict, Set

# user_db.py와 classroom_db.py에서 함수 가져오기
from user_db import register_user, get_user, get_user_role, Role
from classroom_db import (
    create_classroom, get_classroom, get_all_classrooms,
    update_classroom, delete_classroom
)
from reservation_db import (
    create_reservation, get_user_reservations, 
    get_classroom_reservations, cancel_reservation,
    find_available_classrooms, filter_classrooms, RESERVATIONS
)
from notification_db import (
    create_notification, get_user_notifications, mark_as_read,
    mark_all_as_read, get_unread_count, schedule_reservation_notification,
    check_and_create_notifications
)
from waitlist_db import (
    create_waitlist_entry, get_user_waitlist, cancel_waitlist_entry,
    process_waitlist_on_reservation_cancelled, get_classroom_waitlist
)

app = FastAPI()

# 401 에러(인증 실패) 처리: 로그인 페이지로 리다이렉트
@app.exception_handler(401)
async def unauthorized_handler(request: Request, exc: HTTPException):
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

app.add_middleware(SessionMiddleware, secret_key="your-secret-key-change-in-production")

# Static 파일 서빙 (이미지 등)
app.mount("/static", StaticFiles(directory="."), name="static")

templates = Jinja2Templates(directory="templates")

# WebSocket 연결 관리 (classroom_id -> Set[WebSocket])
classroom_websockets: Dict[int, Set[WebSocket]] = {}

# =============================================================
# 헬퍼 함수
# =============================================================

def get_current_user(request: Request) -> dict | None:
    """현재 로그인한 사용자 정보 반환"""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    
    user = get_user(user_id)
    if user:
        return {
            "user_id": user_id,
            "role": user.get("role")
        }
    return None

def require_auth(request: Request) -> dict:
    """인증이 필요한 엔드포인트에서 사용"""
    user = get_current_user(request)
    if not user:
        # 세션이 만료되었거나 유효하지 않은 경우
        # 예외 핸들러에서 로그인 페이지로 리다이렉트 처리
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return user

def require_admin(request: Request) -> dict:
    """관리자 권한이 필요한 엔드포인트에서 사용"""
    user = require_auth(request)
    if user.get("role") != "Admin":
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    return user

# =============================================================
# 1. 인증 관련 엔드포인트
# =============================================================

# GET: 회원가입 폼 페이지 제공
@app.get("/register", response_class=HTMLResponse)
async def get_register_form(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse("register.html", {"request": request, "error_message": None})

# POST: 폼 데이터 처리 및 사용자 등록
@app.post("/register")
async def post_register(
    request: Request,
    user_id: str = Form(...),
    password: str = Form(...),
    role: Role = Form(...)
):
    if not user_id or not password:
        error_msg = "ID와 비밀번호를 모두 입력해야 합니다."
        return templates.TemplateResponse("register.html", {"request": request, "error_message": error_msg})
    
    if register_user(user_id, password, role):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    else:
        error_msg = f"'{user_id}'는 이미 사용 중인 ID입니다."
        return templates.TemplateResponse("register.html", {"request": request, "error_message": error_msg})

# GET: 로그인 폼 페이지 제공
@app.get("/login", response_class=HTMLResponse)
async def get_login_form(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse("login.html", {"request": request, "error_message": None})

# POST: 폼 데이터 처리 및 사용자 인증
@app.post("/login")
async def post_login(
    request: Request,
    user_id: str = Form(...),
    password: str = Form(...)
):
    user = get_user(user_id)
    
    if not user or user.get("password") != password:
        error_msg = "ID 또는 비밀번호가 올바르지 않습니다."
        return templates.TemplateResponse("login.html", {"request": request, "error_message": error_msg})
    
    # 세션에 사용자 정보 저장
    request.session["user_id"] = user_id
    request.session["role"] = user.get("role")
    
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

# 로그아웃
@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

# 로그아웃 API (AJAX용)
@app.post("/api/logout")
async def logout_api(request: Request):
    """창 닫기 시 자동 로그아웃을 위한 API"""
    request.session.clear()
    return {"success": True}

# =============================================================
# 2. 메인 페이지
# =============================================================

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    # 내 예약 목록 가져오기
    reservations = get_user_reservations(user["user_id"])
    classrooms = get_all_classrooms()
    
    # 예약 데이터에 강의실 정보 추가
    for reservation in reservations:
        classroom_id = reservation["classroom_id"]
        classroom = get_classroom(classroom_id)
        reservation["classroom_name"] = classroom["name"] if classroom else f"강의실 {classroom_id}"
        reservation["classroom_location"] = classroom["location"] if classroom else ""
        if "participants" not in reservation:
            reservation["participants"] = []
    
    # 최신순으로 정렬 (최대 5개만)
    reservations.sort(key=lambda r: (r["date"], r["start_time"]), reverse=True)
    recent_reservations = reservations[:5]
    
    # 내 대기 신청 목록 가져오기
    waitlist_entries = get_user_waitlist(user["user_id"])
    
    # 대기 신청 데이터에 강의실 정보 추가
    for entry in waitlist_entries:
        classroom_id = entry["classroom_id"]
        classroom = get_classroom(classroom_id)
        entry["classroom_name"] = classroom["name"] if classroom else f"강의실 {classroom_id}"
        entry["classroom_location"] = classroom["location"] if classroom else ""
        
        # 현재 대기 순위 계산
        same_time_entries = get_classroom_waitlist(classroom_id, entry["date"], entry["start_time"])
        entry["current_priority"] = next((i+1 for i, e in enumerate(same_time_entries) if e["id"] == entry["id"]), entry["priority"] + 1)
    
    # 최신순으로 정렬 (최대 5개만)
    waitlist_entries.sort(key=lambda e: (e["date"], e["start_time"]), reverse=True)
    recent_waitlist = waitlist_entries[:5]
    
    # 최근 알림 5개 가져오기
    recent_notifications = get_user_notifications(user["user_id"], unread_only=False)[:5]
    unread_count = get_unread_count(user["user_id"])
    
    # 예약 성공 플래그 확인
    show_success_popup = request.session.pop("reservation_success", False)
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": user,
        "reservations": recent_reservations,
        "waitlist_entries": recent_waitlist,
        "recent_notifications": recent_notifications,
        "unread_count": unread_count,
        "show_success_popup": show_success_popup
    })

# =============================================================
# 3. 강의실 관리
# =============================================================

# 강의실 목록 조회 (모든 로그인 사용자 가능)
@app.get("/classrooms", response_class=HTMLResponse)
async def list_classrooms(request: Request):
    require_auth(request)  # 로그인만 필요 (학생도 조회 가능)
    classrooms = get_all_classrooms()
    return templates.TemplateResponse("classrooms.html", {
        "request": request,
        "classrooms": classrooms,
        "user": get_current_user(request)
    })

# 강의실 생성 폼
@app.get("/classrooms/create", response_class=HTMLResponse)
async def create_classroom_form(request: Request):
    require_admin(request)
    return templates.TemplateResponse("classroom_form.html", {
        "request": request,
        "user": get_current_user(request),
        "classroom": None,
        "mode": "create"
    })

# 강의실 생성
@app.post("/classrooms/create")
async def create_classroom_post(
    request: Request,
    name: str = Form(...),
    location: str = Form(...),
    capacity: int = Form(...),
    projector: bool = Form(default=False),
    whiteboard: bool = Form(default=False)
):
    require_admin(request)
    
    equipment = {}
    if projector:
        equipment["projector"] = True
    if whiteboard:
        equipment["whiteboard"] = True
    
    classroom_id = create_classroom(name, location, capacity, equipment)
    return RedirectResponse(url="/classrooms", status_code=status.HTTP_303_SEE_OTHER)

# 강의실 수정 폼
@app.get("/classrooms/{classroom_id}/edit", response_class=HTMLResponse)
async def edit_classroom_form(request: Request, classroom_id: int):
    require_admin(request)
    classroom = get_classroom(classroom_id)
    if not classroom:
        raise HTTPException(status_code=404, detail="강의실을 찾을 수 없습니다.")
    
    return templates.TemplateResponse("classroom_form.html", {
        "request": request,
        "user": get_current_user(request),
        "classroom": classroom,
        "classroom_id": classroom_id,
        "mode": "edit"
    })

# 강의실 수정
@app.post("/classrooms/{classroom_id}/edit")
async def edit_classroom_post(
    request: Request,
    classroom_id: int,
    name: str = Form(...),
    location: str = Form(...),
    capacity: int = Form(...),
    projector: bool = Form(default=False),
    whiteboard: bool = Form(default=False)
):
    require_admin(request)
    
    equipment = {}
    if projector:
        equipment["projector"] = True
    if whiteboard:
        equipment["whiteboard"] = True
    
    if not update_classroom(classroom_id, name, location, capacity, equipment):
        raise HTTPException(status_code=404, detail="강의실을 찾을 수 없습니다.")
    
    return RedirectResponse(url="/classrooms", status_code=status.HTTP_303_SEE_OTHER)

# 강의실 삭제
@app.post("/classrooms/{classroom_id}/delete")
async def delete_classroom_post(request: Request, classroom_id: int):
    require_admin(request)
    
    if not delete_classroom(classroom_id):
        raise HTTPException(status_code=404, detail="강의실을 찾을 수 없습니다.")
    
    return RedirectResponse(url="/classrooms", status_code=status.HTTP_303_SEE_OTHER)

# =============================================================
# 4. 예약 관리
# =============================================================

# 예약 생성 폼
@app.get("/reservations/create", response_class=HTMLResponse)
async def create_reservation_form(request: Request, classroom_id: int = Query(None)):
    user = require_auth(request)  # 로그인 사용자만 예약 가능
    classrooms = get_all_classrooms()
    
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    max_date = datetime.fromordinal(datetime.now().toordinal() + 6).strftime("%Y-%m-%d")
    
    return templates.TemplateResponse("reservation_form.html", {
        "request": request,
        "user": user,
        "classrooms": classrooms,
        "error_message": None,
        "selected_classroom_id": classroom_id,
        "selected_date": None,
        "selected_start_time": None,
        "selected_end_time": None,
        "selected_participants": "",
        "today": today,
        "max_date": max_date
    })

# 예약 생성
@app.post("/reservations/create")
async def create_reservation_post(
    request: Request,
    classroom_id: int = Form(...),
    date: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    participants: str = Form(default="")
):
    user = require_auth(request)
    classrooms = get_all_classrooms()
    
    # 강의실 존재 확인
    if classroom_id not in classrooms:
        return templates.TemplateResponse("reservation_form.html", {
            "request": request,
            "user": user,
            "classrooms": classrooms,
            "error_message": "존재하지 않는 강의실입니다.",
            "selected_classroom_id": classroom_id,
            "selected_date": date,
            "selected_start_time": start_time,
            "selected_end_time": end_time,
            "selected_participants": participants
        })
    
    # 참여 인원 파싱 (쉼표로 구분)
    participants_list = []
    if participants:
        participants_list = [p.strip() for p in participants.split(",") if p.strip()]
    
    # 참여 인원 수용인원 초과 검증
    classroom = get_classroom(classroom_id)
    total_people = 1 + len(participants_list)  # 예약자 + 참여 인원
    if classroom and total_people > classroom.get("capacity", 0):
        return templates.TemplateResponse("reservation_form.html", {
            "request": request,
            "user": user,
            "classrooms": classrooms,
            "error_message": f"총 인원({total_people}명)이 강의실 최대 수용인원({classroom.get('capacity', 0)}명)을 초과합니다.",
            "selected_classroom_id": classroom_id,
            "selected_date": date,
            "selected_start_time": start_time,
            "selected_end_time": end_time,
            "selected_participants": participants
        })
    
    # 예약 생성 시도
    success, message = create_reservation(
        user["user_id"],
        classroom_id,
        date,
        start_time,
        end_time,
        participants_list
    )
    
    if success:
        # 예약 생성 성공 시 예약 ID 가져오기
        from reservation_db import RESERVATIONS
        reservation_id = max(RESERVATIONS.keys()) if RESERVATIONS else None
        
        # WebSocket을 통해 해당 강의실 타임라인 보는 사용자들에게 실시간 업데이트 전송
        if classroom_id in classroom_websockets:
            update_message = {
                "type": "reservation_created",
                "classroom_id": classroom_id,
                "date": date,
                "start_time": start_time,
                "end_time": end_time,
                "user_id": user["user_id"],
                "user_name": user["user_id"]  # 사용자 이름 (현재는 ID를 사용)
            }
            disconnected = set()
            for ws in classroom_websockets[classroom_id]:
                try:
                    await ws.send_json(update_message)
                except:
                    disconnected.add(ws)
            # 끊어진 연결 제거
            classroom_websockets[classroom_id] -= disconnected
        
        # 예약 성공 플래그를 세션에 저장하고 메인으로 리다이렉트
        request.session["reservation_success"] = True
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    else:
        # 예약 실패 시 해당 시간대에 예약이 이미 있는지 확인 (시간 충돌인 경우 대기 신청 가능)
        can_waitlist = False
        conflict_keywords = ["이미 예약이 존재합니다", "이미 예약이 있습니다", "다른 이용자의 예약이 존재합니다"]
        is_time_conflict = any(keyword in message for keyword in conflict_keywords)
        
        if is_time_conflict:
            # 해당 시간대에 예약이 있는지 확인
            from reservation_db import get_classroom_reservations
            from reservation_db import _parse_time, _is_time_overlap
            existing_reservations = get_classroom_reservations(classroom_id, date)
            
            try:
                start_time_obj = _parse_time(start_time)
                end_time_obj = _parse_time(end_time)
                
                for reservation in existing_reservations:
                    existing_start = _parse_time(reservation["start_time"])
                    existing_end = _parse_time(reservation["end_time"])
                    
                    if _is_time_overlap(start_time_obj, end_time_obj, existing_start, existing_end):
                        can_waitlist = True
                        break
            except:
                pass
        
        return templates.TemplateResponse("reservation_form.html", {
            "request": request,
            "user": user,
            "classrooms": classrooms,
            "error_message": message,
            "selected_classroom_id": classroom_id,
            "selected_date": date,
            "selected_start_time": start_time,
            "selected_end_time": end_time,
            "selected_participants": participants,
            "can_waitlist": can_waitlist,
            "waitlist_classroom_id": classroom_id if can_waitlist else None,
            "waitlist_date": date if can_waitlist else None,
            "waitlist_start_time": start_time if can_waitlist else None,
            "waitlist_end_time": end_time if can_waitlist else None
        })

# 내 예약 조회
@app.get("/reservations", response_class=HTMLResponse)
async def list_my_reservations(request: Request):
    user = require_auth(request)
    reservations = get_user_reservations(user["user_id"])
    classrooms = get_all_classrooms()
    
    # 예약 데이터에 강의실 정보 추가
    for reservation in reservations:
        classroom_id = reservation["classroom_id"]
        classroom = get_classroom(classroom_id)
        reservation["classroom_name"] = classroom["name"] if classroom else f"강의실 {classroom_id}"
        reservation["classroom_location"] = classroom["location"] if classroom else ""
        # participants 필드가 없으면 빈 리스트로 설정
        if "participants" not in reservation:
            reservation["participants"] = []
    
    # 날짜와 시간 순으로 정렬 (최신순)
    reservations.sort(key=lambda r: (r["date"], r["start_time"]), reverse=True)
    
    return templates.TemplateResponse("my_reservations.html", {
        "request": request,
        "user": user,
        "reservations": reservations
    })

# 강의실별 예약 현황 (타임라인)
@app.get("/classrooms/{classroom_id}/reservations", response_class=HTMLResponse)
async def classroom_reservations_timeline(request: Request, classroom_id: int, date: str = Query(None)):
    user = require_auth(request)
    classroom = get_classroom(classroom_id)
    
    if not classroom:
        raise HTTPException(status_code=404, detail="강의실을 찾을 수 없습니다.")
    
    # 날짜가 지정되지 않았으면 오늘 날짜 사용
    if not date:
        from datetime import datetime
        date = datetime.now().strftime("%Y-%m-%d")
    
    reservations = get_classroom_reservations(classroom_id, date)
    
    # 예약 데이터에 사용자 정보 추가 (선택적)
    from user_db import get_user
    for reservation in reservations:
        user_info = get_user(reservation["user_id"])
        reservation["user_name"] = reservation["user_id"]  # 사용자 ID를 이름으로 사용
    
    # 해당 날짜의 모든 시간대에 대한 대기 신청 목록 가져오기 (24시간 모두 체크)
    waitlist_by_time = {}
    for hour in range(24):
        hour_str = f"{hour:02d}:00"
        waitlist_entries = get_classroom_waitlist(classroom_id, date, hour_str)
        if waitlist_entries:
            key = f"{date}_{hour_str}"
            waitlist_by_time[key] = waitlist_entries
    
    return templates.TemplateResponse("classroom_reservations.html", {
        "request": request,
        "user": user,
        "classroom": classroom,
        "classroom_id": classroom_id,
        "reservations": reservations,
        "selected_date": date,
        "waitlist_by_time": waitlist_by_time
    })

# 예약 취소
@app.post("/reservations/{reservation_id}/cancel")
async def cancel_reservation_post(request: Request, reservation_id: int, from_main: str = Form(default="")):
    user = require_auth(request)
    
    # 취소 전 예약 정보 가져오기
    from reservation_db import get_reservation
    reservation = get_reservation(reservation_id)
    
    success, message = cancel_reservation(reservation_id, user["user_id"])
    
    if success and reservation:
        classroom_id = reservation["classroom_id"]
        date = reservation["date"]
        start_time = reservation["start_time"]
        end_time = reservation["end_time"]
        
        # 대기열 처리 (자동 예약 할당)
        auto_reservation = process_waitlist_on_reservation_cancelled(
            classroom_id, date, start_time, end_time
        )
        
        # WebSocket을 통해 해당 강의실 타임라인 보는 사용자들에게 실시간 업데이트 전송
        if classroom_id in classroom_websockets:
            if auto_reservation:
                # 자동 예약이 생성된 경우
                update_message = {
                    "type": "reservation_created",
                    "classroom_id": classroom_id,
                    "date": date,
                    "start_time": start_time,
                    "end_time": end_time,
                    "user_id": auto_reservation["user_id"],
                    "user_name": auto_reservation["user_id"],  # 사용자 이름 (현재는 ID를 사용)
                    "from_waitlist": True
                }
            else:
                # 예약만 취소된 경우
                update_message = {
                    "type": "reservation_cancelled",
                    "classroom_id": classroom_id,
                    "date": date,
                    "start_time": start_time,
                    "end_time": end_time
                }
            
            disconnected = set()
            for ws in classroom_websockets[classroom_id]:
                try:
                    await ws.send_json(update_message)
                except:
                    disconnected.add(ws)
            # 끊어진 연결 제거
            classroom_websockets[classroom_id] -= disconnected
        
        # 메인 화면에서 왔는지 확인 (from_main 파라미터 또는 referer)
        referer = request.headers.get("referer", "")
        
        # 메인 화면에서 온 경우 메인으로 리다이렉트
        if from_main == "true":
            return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        elif referer:
            from urllib.parse import urlparse
            parsed_referer = urlparse(referer)
            referer_path = parsed_referer.path
            
            # 메인 화면에서 온 경우
            if referer_path == "/" or referer_path == "":
                return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        
        return RedirectResponse(url="/reservations", status_code=status.HTTP_303_SEE_OTHER)
    else:
        # 에러 메시지와 함께 내 예약 페이지로 리다이렉트 (간단한 구현)
        reservations = get_user_reservations(user["user_id"])
        classrooms = get_all_classrooms()
        
        for reservation in reservations:
            classroom_id = reservation["classroom_id"]
            classroom = get_classroom(classroom_id)
            reservation["classroom_name"] = classroom["name"] if classroom else f"강의실 {classroom_id}"
            reservation["classroom_location"] = classroom["location"] if classroom else ""
        
        reservations.sort(key=lambda r: (r["date"], r["start_time"]), reverse=True)
        
        return templates.TemplateResponse("my_reservations.html", {
            "request": request,
            "user": user,
            "reservations": reservations,
            "error_message": message
        })

# 빈 강의실 검색
@app.get("/search/classrooms", response_class=HTMLResponse)
async def search_available_classrooms_form(request: Request):
    user = require_auth(request)
    
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    max_date = datetime.fromordinal(datetime.now().toordinal() + 6).strftime("%Y-%m-%d")
    
    return templates.TemplateResponse("search_classrooms.html", {
        "request": request,
        "user": user,
        "today": today,
        "max_date": max_date,
        "classrooms": [],
        "search_performed": False
    })

@app.post("/search/classrooms", response_class=HTMLResponse)
async def search_available_classrooms_post(
    request: Request,
    date: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    min_capacity: int = Form(default=None),
    has_projector: bool = Form(default=False),
    has_whiteboard: bool = Form(default=False)
):
    user = require_auth(request)
    
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    max_date = datetime.fromordinal(datetime.now().toordinal() + 6).strftime("%Y-%m-%d")
    
    # 빈 강의실 검색
    available_classroom_ids = find_available_classrooms(date, start_time, end_time)
    
    # 필터링 적용
    min_cap = min_capacity if min_capacity and min_capacity > 0 else None
    projector_filter = has_projector if has_projector else None
    whiteboard_filter = has_whiteboard if has_whiteboard else None
    
    filtered_classroom_ids = filter_classrooms(
        available_classroom_ids,
        min_capacity=min_cap,
        has_projector=projector_filter,
        has_whiteboard=whiteboard_filter
    )
    
    # 강의실 정보 가져오기
    all_classrooms = get_all_classrooms()
    filtered_classrooms = {cid: all_classrooms[cid] for cid in filtered_classroom_ids if cid in all_classrooms}
    
    return templates.TemplateResponse("search_classrooms.html", {
        "request": request,
        "user": user,
        "today": today,
        "max_date": max_date,
        "classrooms": filtered_classrooms,
        "search_performed": True,
        "search_date": date,
        "search_start_time": start_time,
        "search_end_time": end_time,
        "search_min_capacity": min_cap,
        "search_has_projector": has_projector,
        "search_has_whiteboard": has_whiteboard
    })

# =============================================================
# 5. WebSocket 실시간 업데이트
# =============================================================

@app.websocket("/ws/classroom/{classroom_id}")
async def websocket_classroom_timeline(websocket: WebSocket, classroom_id: int):
    """강의실 타임라인 실시간 업데이트를 위한 WebSocket 연결"""
    await websocket.accept()
    
    # 연결을 해당 강의실의 WebSocket 목록에 추가
    if classroom_id not in classroom_websockets:
        classroom_websockets[classroom_id] = set()
    classroom_websockets[classroom_id].add(websocket)
    
    try:
        # 연결 유지
        while True:
            data = await websocket.receive_text()
            # 클라이언트로부터 받은 메시지 처리 (필요시)
            # 현재는 단순히 연결 유지만 수행
    except WebSocketDisconnect:
        # 연결 종료 시 목록에서 제거
        if classroom_id in classroom_websockets:
            classroom_websockets[classroom_id].discard(websocket)
            if not classroom_websockets[classroom_id]:
                del classroom_websockets[classroom_id]

# =============================================================
# 6. 알림 관리
# =============================================================

# 알림 조회
@app.get("/notifications", response_class=HTMLResponse)
async def list_notifications(request: Request, unread_only: bool = Query(False)):
    user = require_auth(request)
    notifications = get_user_notifications(user["user_id"], unread_only=unread_only)
    unread_count = get_unread_count(user["user_id"])
    
    return templates.TemplateResponse("notifications.html", {
        "request": request,
        "user": user,
        "notifications": notifications,
        "unread_count": unread_count,
        "unread_only": unread_only
    })

# 알림 읽음 처리
@app.post("/notifications/{notification_id}/read")
async def mark_notification_read(request: Request, notification_id: int):
    user = require_auth(request)
    success = mark_as_read(notification_id, user["user_id"])
    
    if success:
        return RedirectResponse(url="/notifications", status_code=status.HTTP_303_SEE_OTHER)
    else:
        raise HTTPException(status_code=404, detail="알림을 찾을 수 없습니다.")

# 모든 알림 읽음 처리
@app.post("/notifications/read-all")
async def mark_all_notifications_read(request: Request):
    user = require_auth(request)
    mark_all_as_read(user["user_id"])
    return RedirectResponse(url="/notifications", status_code=status.HTTP_303_SEE_OTHER)

# 알림 개수 API (AJAX용)
@app.get("/api/notifications/unread-count")
async def get_notification_count(request: Request):
    user = get_current_user(request)
    if not user:
        return {"count": 0}
    
    count = get_unread_count(user["user_id"])
    return {"count": count}

# =============================================================
# 백그라운드 작업: 알림 체크
# =============================================================

async def periodic_notification_check():
    """주기적으로 알림을 체크하고 생성하는 백그라운드 작업"""
    while True:
        try:
            check_and_create_notifications()
        except Exception:
            pass  # 에러 발생 시 무시하고 계속 실행
        await asyncio.sleep(60)  # 1분마다 체크

@app.on_event("startup")
async def startup_event():
    """서버 시작 시 백그라운드 작업 시작"""
    asyncio.create_task(periodic_notification_check())

# =============================================================
# 7. 대기열 관리
# =============================================================

# 대기 신청
@app.post("/waitlist/create")
async def create_waitlist_post(
    request: Request,
    classroom_id: int = Form(...),
    date: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...)
):
    user = require_auth(request)
    
    success, message = create_waitlist_entry(
        user["user_id"],
        classroom_id,
        date,
        start_time,
        end_time
    )
    
    if success:
        return RedirectResponse(url=f"/classrooms/{classroom_id}/reservations?date={date}", status_code=status.HTTP_303_SEE_OTHER)
    else:
        # 에러 메시지와 함께 타임라인 페이지로 리다이렉트
        classroom = get_classroom(classroom_id)
        if not classroom:
            raise HTTPException(status_code=404, detail="강의실을 찾을 수 없습니다.")
        
        reservations = get_classroom_reservations(classroom_id, date)
        waitlist_entries = get_classroom_waitlist(classroom_id, date, start_time)
        
        from user_db import get_user
        for reservation in reservations:
            reservation["user_name"] = reservation["user_id"]
        
        return templates.TemplateResponse("classroom_reservations.html", {
            "request": request,
            "user": user,
            "classroom": classroom,
            "classroom_id": classroom_id,
            "reservations": reservations,
            "selected_date": date,
            "error_message": message,
            "waitlist_entries": waitlist_entries
        })

# 대기 신청 취소
@app.post("/waitlist/{waitlist_id}/cancel")
async def cancel_waitlist_post(request: Request, waitlist_id: int, from_main: str = Form(default="")):
    user = require_auth(request)
    
    success, message = cancel_waitlist_entry(waitlist_id, user["user_id"])
    
    if success:
        # 메인 화면에서 왔는지 확인
        referer = request.headers.get("referer", "")
        
        # 메인 화면에서 온 경우 메인으로 리다이렉트
        if from_main == "true":
            return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        elif referer:
            from urllib.parse import urlparse
            parsed_referer = urlparse(referer)
            referer_path = parsed_referer.path
            
            # 메인 화면에서 온 경우
            if referer_path == "/" or referer_path == "":
                return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        
        # 대기 신청 정보 가져오기
        from waitlist_db import get_waitlist_entry
        entry = get_waitlist_entry(waitlist_id)
        if entry:
            return RedirectResponse(url=f"/classrooms/{entry['classroom_id']}/reservations?date={entry['date']}", status_code=status.HTTP_303_SEE_OTHER)
    
    return RedirectResponse(url="/waitlist", status_code=status.HTTP_303_SEE_OTHER)

# 내 대기 신청 조회
@app.get("/waitlist", response_class=HTMLResponse)
async def list_my_waitlist(request: Request):
    user = require_auth(request)
    waitlist_entries = get_user_waitlist(user["user_id"])
    classrooms = get_all_classrooms()
    
    # 대기 신청 데이터에 강의실 정보 추가
    for entry in waitlist_entries:
        classroom_id = entry["classroom_id"]
        classroom = get_classroom(classroom_id)
        entry["classroom_name"] = classroom["name"] if classroom else f"강의실 {classroom_id}"
        entry["classroom_location"] = classroom["location"] if classroom else ""
        
        # 현재 대기 순위 계산
        same_time_entries = get_classroom_waitlist(classroom_id, entry["date"], entry["start_time"])
        entry["current_priority"] = next((i+1 for i, e in enumerate(same_time_entries) if e["id"] == entry["id"]), entry["priority"] + 1)
    
    return templates.TemplateResponse("my_waitlist.html", {
        "request": request,
        "user": user,
        "waitlist_entries": waitlist_entries
    })

# =============================================================
# 8. 통계
# =============================================================

# 가장 인기 많은 강의실 Top 5 통계 API
@app.get("/api/stats/popular-classrooms")
async def get_popular_classrooms_stats(request: Request):
    """관리자용 인기 강의실 통계 API"""
    user = get_current_user(request)
    if not user or user.get("role") != "Admin":
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    
    from reservation_db import RESERVATIONS
    from classroom_db import get_all_classrooms
    
    # 강의실별 예약 개수 집계
    classroom_counts = {}
    for reservation in RESERVATIONS.values():
        classroom_id = reservation["classroom_id"]
        classroom_counts[classroom_id] = classroom_counts.get(classroom_id, 0) + 1
    
    # Top 5 추출
    top_classrooms = sorted(classroom_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # 강의실 정보 추가
    all_classrooms = get_all_classrooms()
    result = []
    for classroom_id, count in top_classrooms:
        classroom = all_classrooms.get(classroom_id)
        if classroom:
            result.append({
                "classroom_id": classroom_id,
                "name": classroom["name"],
                "location": classroom["location"],
                "reservation_count": count
            })
    
    return {"classrooms": result}

# 통계 페이지
@app.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request):
    """관리자용 통계 페이지"""
    user = require_admin(request)
    
    # Top 5 인기 강의실
    from reservation_db import RESERVATIONS
    from classroom_db import get_all_classrooms
    
    classroom_counts = {}
    for reservation in RESERVATIONS.values():
        classroom_id = reservation["classroom_id"]
        classroom_counts[classroom_id] = classroom_counts.get(classroom_id, 0) + 1
    
    top_classrooms = sorted(classroom_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    
    all_classrooms = get_all_classrooms()
    popular_classrooms = []
    for classroom_id, count in top_classrooms:
        classroom = all_classrooms.get(classroom_id)
        if classroom:
            popular_classrooms.append({
                "id": classroom_id,
                "name": classroom["name"],
                "location": classroom["location"],
                "count": count
            })
    
    return templates.TemplateResponse("stats.html", {
        "request": request,
        "user": user,
        "popular_classrooms": popular_classrooms
    })
