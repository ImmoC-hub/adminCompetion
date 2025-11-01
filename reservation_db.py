import json
import os
from datetime import datetime, date, time
from typing import Optional, List

# 예약 데이터 저장소
# 구조: {reservation_id: {"user_id": str, "classroom_id": int, "date": str, "start_time": str, "end_time": str, "participants": List[str]}}
RESERVATIONS_FILE = "reservations.json"
RESERVATIONS: dict[int, dict] = {}
_next_id = 1

def _load_reservations() -> tuple[dict[int, dict], int]:
    """파일에서 예약 데이터 로드"""
    if os.path.exists(RESERVATIONS_FILE):
        try:
            with open(RESERVATIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                reservations = {int(k): v for k, v in data.get("reservations", {}).items()}
                next_id = data.get("next_id", 1)
                return reservations, next_id
        except (json.JSONDecodeError, IOError, ValueError, KeyError):
            return {}, 1
    return {}, 1

def _save_reservations() -> None:
    """예약 데이터를 파일에 저장"""
    try:
        data = {
            "reservations": {str(k): v for k, v in RESERVATIONS.items()},
            "next_id": _next_id
        }
        with open(RESERVATIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except IOError:
        pass

# 서버 시작 시 데이터 로드
loaded_reservations, loaded_next_id = _load_reservations()
RESERVATIONS.update(loaded_reservations)
_next_id = loaded_next_id

def _parse_time(time_str: str) -> time:
    """시간 문자열을 time 객체로 변환 (예: "14:00" -> time(14, 0))"""
    try:
        hour, minute = map(int, time_str.split(":"))
        return time(hour, minute)
    except (ValueError, AttributeError):
        raise ValueError(f"잘못된 시간 형식: {time_str}")

def _parse_date(date_str: str) -> date:
    """날짜 문자열을 date 객체로 변환 (예: "2024-01-15" -> date(2024, 1, 15))"""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise ValueError(f"잘못된 날짜 형식: {date_str}")

def _is_past_datetime(reservation_date: date, start_time: time) -> bool:
    """예약 날짜와 시간이 과거인지 확인"""
    now = datetime.now()
    reservation_datetime = datetime.combine(reservation_date, start_time)
    return reservation_datetime < now

def _is_within_7_days(reservation_date: date) -> bool:
    """예약 날짜가 오늘부터 7일 이내인지 확인 (최대 7일 전 = 오늘+6일)"""
    today = date.today()
    max_date = date.fromordinal(today.toordinal() + 6)  # 오늘+6일
    return today <= reservation_date <= max_date

def count_active_reservations(user_id: str) -> int:
    """사용자의 활성화된 예약(미래 예약) 개수를 반환"""
    now = datetime.now()
    count = 0
    for reservation in RESERVATIONS.values():
        if reservation["user_id"] == user_id:
            reservation_date_obj = _parse_date(reservation["date"])
            start_time_obj = _parse_time(reservation["start_time"])
            reservation_datetime = datetime.combine(reservation_date_obj, start_time_obj)
            if reservation_datetime >= now:
                count += 1
        # 참여 인원으로 포함된 예약도 카운트
        participants = reservation.get("participants", [])
        if user_id in participants:
            reservation_date_obj = _parse_date(reservation["date"])
            start_time_obj = _parse_time(reservation["start_time"])
            reservation_datetime = datetime.combine(reservation_date_obj, start_time_obj)
            if reservation_datetime >= now:
                count += 1
    return count

def _is_valid_time_slot(start_time: time, end_time: time) -> bool:
    """정시~정시 1시간 단위로 연속된 예약인지 확인 (당일 자정까지)"""
    # 시작 시간과 종료 시간이 정시(분이 0)인지 확인
    if start_time.minute != 0 or end_time.minute != 0:
        return False
    
    # 시작 시간이 종료 시간보다 이전이어야 함
    if start_time >= end_time:
        return False
    
    # 종료 시간이 자정(00:00)이면 다음날이므로 당일이 아님 - 허용하지 않음
    # 하지만 23:00~00:00은 당일 자정까지이므로 특별 처리
    if end_time.hour == 0 and end_time.minute == 0:
        # 23:00~00:00은 허용
        if start_time.hour == 23:
            return True
        # 그 외의 경우는 다음날이므로 불가
        return False
    
    # 시간 차이가 1시간의 배수인지 확인 (당일 자정(23:59)까지)
    start_hour = start_time.hour
    end_hour = end_time.hour
    
    # 종료 시간이 시작 시간보다 이전이면 안 됨 (당일 내에서)
    if end_hour <= start_hour:
        return False
    
    # 시간 차이가 1시간 이상이어야 함
    time_diff = end_hour - start_hour
    return time_diff > 0

def _is_time_overlap(start1: time, end1: time, start2: time, end2: time) -> bool:
    """두 시간 구간이 겹치는지 확인"""
    # 시간 객체를 비교 가능한 형태로 변환 (분 단위로)
    def time_to_minutes(t: time) -> int:
        return t.hour * 60 + t.minute
    
    start1_min = time_to_minutes(start1)
    end1_min = time_to_minutes(end1)
    start2_min = time_to_minutes(start2)
    end2_min = time_to_minutes(end2)
    
    # 겹치는 경우: start1 < end2 and start2 < end1
    return start1_min < end2_min and start2_min < end1_min

def create_reservation(user_id: str, classroom_id: int, reservation_date: str, start_time_str: str, end_time_str: str, participants: Optional[List[str]] = None) -> tuple[bool, str]:
    """
    예약을 생성하고 성공 여부와 메시지를 반환
    
    Returns:
        (success: bool, message: str)
    """
    global _next_id
    
    # 1. 날짜 및 시간 파싱
    try:
        reservation_date_obj = _parse_date(reservation_date)
        start_time_obj = _parse_time(start_time_str)
        end_time_obj = _parse_time(end_time_str)
    except ValueError as e:
        return False, str(e)
    
    # 2. 정책 검증: 과거 시간 예약 불가
    if _is_past_datetime(reservation_date_obj, start_time_obj):
        return False, "과거 시간은 예약할 수 없습니다."
    
    # 3. 정책 검증: 최대 7일 전까지만 예약 가능 (오늘+6일)
    if not _is_within_7_days(reservation_date_obj):
        return False, "예약은 오늘부터 최대 7일 후까지만 가능합니다. (오늘+6일)"
    
    # 4. 정책 검증: 1시간 단위 정시~정시로 연속 예약 가능 (당일 자정까지)
    if not _is_valid_time_slot(start_time_obj, end_time_obj):
        return False, "예약은 정시~정시 1시간 단위로 연속 예약이 가능합니다. (예: 14:00~15:00, 14:00~17:00)"
    
    # 당일 자정(00:00) 이후로 예약할 수 없음 (23:59까지)
    if end_time_obj.hour == 0 and end_time_obj.minute == 0:
        # 다음날 자정은 허용 (23:00~00:00)
        pass
    
    # 5. 정책 검증: 예약자 본인의 활성 예약 개수 확인 (최대 3개)
    active_count = count_active_reservations(user_id)
    if active_count >= 3:
        return False, "1인당 활성화된 예약은 최대 3개까지 가능합니다."
    
    # 6. 참여 인원 처리 및 검증
    participants = participants or []
    # 참여 인원 중 중복 제거 및 예약자 제외
    participants = list(set([p.strip() for p in participants if p.strip() and p.strip() != user_id]))
    
    # 참여 인원의 활성 예약 개수 확인
    for participant_id in participants:
        from user_db import get_user
        # 참여 인원이 회원인지 확인
        participant_user = get_user(participant_id)
        if participant_user:
            participant_active_count = count_active_reservations(participant_id)
            if participant_active_count >= 3:
                return False, f"참여 인원 '{participant_id}'의 활성 예약이 이미 3개입니다."
    
    # 7. 해당 강의실의 같은 날짜 예약들 확인
    conflicting_reservations = []
    for reservation in RESERVATIONS.values():
        if (reservation["classroom_id"] == classroom_id and 
            reservation["date"] == reservation_date):
            existing_start = _parse_time(reservation["start_time"])
            existing_end = _parse_time(reservation["end_time"])
            
            # 시간 겹침 확인
            if _is_time_overlap(start_time_obj, end_time_obj, existing_start, existing_end):
                conflicting_reservations.append({
                    "start": reservation["start_time"],
                    "end": reservation["end_time"],
                    "user": reservation["user_id"]
                })
    
    if conflicting_reservations:
        # 충돌하는 예약이 있으면 구체적으로 설명
        conflict_messages = []
        for conf in conflicting_reservations:
            conflict_messages.append(f"{conf['start']}~{conf['end']} (예약자: {conf['user']})")
        conflict_text = ", ".join(conflict_messages)
        return False, f"예약하려는 시간({start_time_str}~{end_time_str}) 사이에 다른 이용자의 예약이 존재합니다. 충돌하는 예약: {conflict_text}"
    
    # 5. 예약 생성
    reservation_id = _next_id
    _next_id += 1
    
    RESERVATIONS[reservation_id] = {
        "user_id": user_id,
        "classroom_id": classroom_id,
        "date": reservation_date,
        "start_time": start_time_str,
        "end_time": end_time_str,
        "participants": participants
    }
    _save_reservations()
    
    return True, "예약이 성공적으로 생성되었습니다."

def get_reservation(reservation_id: int) -> Optional[dict]:
    """예약 정보를 조회"""
    return RESERVATIONS.get(reservation_id)

def get_user_reservations(user_id: str) -> List[dict]:
    """특정 사용자의 모든 예약을 조회 (본인이 생성한 예약 + 참여 인원으로 포함된 예약)"""
    user_reservations = []
    for res_id, reservation in RESERVATIONS.items():
        # 본인이 생성한 예약
        if reservation["user_id"] == user_id:
            user_reservations.append({**reservation, "id": res_id, "is_owner": True})
        # 참여 인원으로 포함된 예약
        elif user_id in reservation.get("participants", []):
            user_reservations.append({**reservation, "id": res_id, "is_owner": False})
    return user_reservations

def get_classroom_reservations(classroom_id: int, date: Optional[str] = None) -> List[dict]:
    """특정 강의실의 예약을 조회 (날짜 필터링 옵션)"""
    reservations = [
        {**reservation, "id": res_id}
        for res_id, reservation in RESERVATIONS.items()
        if reservation["classroom_id"] == classroom_id
    ]
    
    if date:
        reservations = [r for r in reservations if r["date"] == date]
    
    # 날짜와 시간 순으로 정렬
    reservations.sort(key=lambda r: (r["date"], r["start_time"]))
    return reservations

def cancel_reservation(reservation_id: int, user_id: str) -> tuple[bool, str]:
    """예약을 취소 (본인 예약만 취소 가능)"""
    if reservation_id not in RESERVATIONS:
        return False, "존재하지 않는 예약입니다."
    
    reservation = RESERVATIONS[reservation_id]
    if reservation["user_id"] != user_id:
        return False, "본인의 예약만 취소할 수 있습니다."
    
    del RESERVATIONS[reservation_id]
    _save_reservations()
    return True, "예약이 취소되었습니다."

def delete_reservation(reservation_id: int) -> bool:
    """예약을 삭제 (관리자용)"""
    if reservation_id in RESERVATIONS:
        del RESERVATIONS[reservation_id]
        _save_reservations()
        return True
    return False

def find_available_classrooms(reservation_date: str, start_time_str: str, end_time_str: str) -> List[int]:
    """특정 날짜와 시간에 예약 가능한 강의실 ID 목록 반환"""
    try:
        reservation_date_obj = _parse_date(reservation_date)
        start_time_obj = _parse_time(start_time_str)
        end_time_obj = _parse_time(end_time_str)
    except ValueError:
        return []
    
    if not _is_valid_time_slot(start_time_obj, end_time_obj):
        return []
    
    # 모든 강의실 ID를 가져옴
    from classroom_db import get_all_classrooms
    all_classrooms = get_all_classrooms()
    available_classroom_ids = []
    
    for classroom_id in all_classrooms.keys():
        is_available = True
        # 해당 강의실의 같은 날짜 예약들 확인
        for reservation in RESERVATIONS.values():
            if (reservation["classroom_id"] == classroom_id and 
                reservation["date"] == reservation_date):
                existing_start = _parse_time(reservation["start_time"])
                existing_end = _parse_time(reservation["end_time"])
                
                # 시간 겹침 확인
                if _is_time_overlap(start_time_obj, end_time_obj, existing_start, existing_end):
                    is_available = False
                    break
        
        if is_available:
            available_classroom_ids.append(classroom_id)
    
    return available_classroom_ids

def filter_classrooms(classroom_ids: List[int], min_capacity: Optional[int] = None, 
                     has_projector: Optional[bool] = None, 
                     has_whiteboard: Optional[bool] = None) -> List[int]:
    """강의실 목록을 필터링"""
    from classroom_db import get_classroom
    
    filtered = []
    for classroom_id in classroom_ids:
        classroom = get_classroom(classroom_id)
        if not classroom:
            continue
        
        # 최소 수용인원 필터
        if min_capacity is not None and classroom.get("capacity", 0) < min_capacity:
            continue
        
        equipment = classroom.get("equipment", {})
        
        # 프로젝터 필터
        if has_projector is not None:
            if has_projector and not equipment.get("projector", False):
                continue
            if not has_projector and equipment.get("projector", False):
                continue
        
        # 화이트보드 필터
        if has_whiteboard is not None:
            if has_whiteboard and not equipment.get("whiteboard", False):
                continue
            if not has_whiteboard and equipment.get("whiteboard", False):
                continue
        
        filtered.append(classroom_id)
    
    return filtered
