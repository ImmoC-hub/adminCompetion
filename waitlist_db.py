import json
import os
from datetime import datetime, date, time
from typing import Optional, List

# 대기열 데이터 저장소
# 구조: {waitlist_id: {"user_id": str, "classroom_id": int, "date": str, "start_time": str, "end_time": str, "created_at": str, "priority": int}}
WAITLIST_FILE = "waitlist.json"
WAITLIST: dict[int, dict] = {}
_next_id = 1

def _load_waitlist() -> tuple[dict[int, dict], int]:
    """파일에서 대기열 데이터 로드"""
    if os.path.exists(WAITLIST_FILE):
        try:
            with open(WAITLIST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                waitlist = {int(k): v for k, v in data.get("waitlist", {}).items()}
                next_id = data.get("next_id", 1)
                return waitlist, next_id
        except (json.JSONDecodeError, IOError, ValueError, KeyError):
            return {}, 1
    return {}, 1

def _save_waitlist() -> None:
    """대기열 데이터를 파일에 저장"""
    try:
        data = {
            "waitlist": {str(k): v for k, v in WAITLIST.items()},
            "next_id": _next_id
        }
        with open(WAITLIST_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except IOError:
        pass

# 서버 시작 시 데이터 로드
loaded_waitlist, loaded_next_id = _load_waitlist()
WAITLIST.update(loaded_waitlist)
_next_id = loaded_next_id

def _parse_time(time_str: str) -> time:
    """시간 문자열을 time 객체로 변환"""
    from reservation_db import _parse_time as reservation_parse_time
    return reservation_parse_time(time_str)

def _parse_date(date_str: str) -> date:
    """날짜 문자열을 date 객체로 변환"""
    from reservation_db import _parse_date as reservation_parse_date
    return reservation_parse_date(date_str)

def create_waitlist_entry(user_id: str, classroom_id: int, reservation_date: str, 
                         start_time_str: str, end_time_str: str) -> tuple[bool, str]:
    """
    대기 신청 생성
    
    Returns:
        (success: bool, message: str)
    """
    global _next_id
    
    from reservation_db import count_active_reservations
    
    # 현재 예약이 3개인지 확인
    active_count = count_active_reservations(user_id)
    if active_count >= 3:
        return False, "현재 활성화된 예약이 3개입니다. 대기 신청을 할 수 없습니다."
    
    # 날짜 및 시간 파싱
    try:
        reservation_date_obj = _parse_date(reservation_date)
        start_time_obj = _parse_time(start_time_str)
        end_time_obj = _parse_time(end_time_str)
    except ValueError as e:
        return False, str(e)
    
    # 시간 충돌 확인은 선택사항 - 대기 신청은 항상 허용
    # 사용자가 설정한 시작/종료 시간으로 대기 신청 등록
    # (시간 충돌 여부와 관계없이 사용자가 원하는 시간대로 대기 신청 가능)
    
    # 이미 대기 신청이 있는지 확인 (같은 강의실, 날짜, 시작/종료 시간 모두 일치하는 경우)
    for entry in WAITLIST.values():
        if (entry["user_id"] == user_id and
            entry["classroom_id"] == classroom_id and
            entry["date"] == reservation_date and
            entry["start_time"] == start_time_str and
            entry["end_time"] == end_time_str):
            return False, "이미 해당 시간대에 대기 신청이 있습니다."
    
    # 우선순위 계산 (같은 강의실, 날짜, 시작/종료 시간의 대기 신청 개수)
    priority = sum(1 for entry in WAITLIST.values()
                   if (entry["classroom_id"] == classroom_id and
                       entry["date"] == reservation_date and
                       entry["start_time"] == start_time_str and
                       entry["end_time"] == end_time_str))
    
    # 대기 신청 생성
    waitlist_id = _next_id
    _next_id += 1
    
    WAITLIST[waitlist_id] = {
        "user_id": user_id,
        "classroom_id": classroom_id,
        "date": reservation_date,
        "start_time": start_time_str,
        "end_time": end_time_str,
        "created_at": datetime.now().isoformat(),
        "priority": priority
    }
    _save_waitlist()
    
    return True, f"대기 신청이 완료되었습니다. (대기 순위: {priority + 1})"

def get_waitlist_entry(waitlist_id: int) -> Optional[dict]:
    """대기 신청 정보 조회"""
    return WAITLIST.get(waitlist_id)

def get_user_waitlist(user_id: str) -> List[dict]:
    """사용자의 대기 신청 목록"""
    entries = [
        {**entry, "id": entry_id}
        for entry_id, entry in WAITLIST.items()
        if entry["user_id"] == user_id
    ]
    # 날짜와 시간 순으로 정렬
    entries.sort(key=lambda e: (e["date"], e["start_time"]))
    return entries

def get_classroom_waitlist(classroom_id: int, date: str, start_time: str) -> List[dict]:
    """특정 강의실의 특정 시간대 대기 신청 목록 (우선순위 순)"""
    entries = [
        {**entry, "id": entry_id}
        for entry_id, entry in WAITLIST.items()
        if (entry["classroom_id"] == classroom_id and
            entry["date"] == date and
            entry["start_time"] == start_time)
    ]
    # 우선순위와 생성 시간 순으로 정렬
    entries.sort(key=lambda e: (e["priority"], e["created_at"]))
    return entries

def cancel_waitlist_entry(waitlist_id: int, user_id: str) -> tuple[bool, str]:
    """대기 신청 취소"""
    if waitlist_id not in WAITLIST:
        return False, "존재하지 않는 대기 신청입니다."
    
    entry = WAITLIST[waitlist_id]
    if entry["user_id"] != user_id:
        return False, "본인의 대기 신청만 취소할 수 있습니다."
    
    # 우선순위 재정렬
    classroom_id = entry["classroom_id"]
    date = entry["date"]
    start_time = entry["start_time"]
    end_time = entry["end_time"]
    
    del WAITLIST[waitlist_id]
    
    # 같은 시간 범위의 다른 대기 신청들의 우선순위 재정렬
    for other_entry in WAITLIST.values():
        if (other_entry["classroom_id"] == classroom_id and
            other_entry["date"] == date and
            other_entry["start_time"] == start_time and
            other_entry["end_time"] == end_time):
            # 우선순위 재계산
            priority = sum(1 for e in WAITLIST.values()
                          if (e["classroom_id"] == classroom_id and
                              e["date"] == date and
                              e["start_time"] == start_time and
                              e["end_time"] == end_time and
                              e["created_at"] < other_entry["created_at"]))
            other_entry["priority"] = priority
    
    _save_waitlist()
    return True, "대기 신청이 취소되었습니다."

def process_waitlist_on_reservation_cancelled(classroom_id: int, date: str, 
                                            start_time: str, end_time: str) -> Optional[dict]:
    """
    예약 취소 시 대기열 처리
    취소된 예약 시간이 대기 신청의 시간 범위 안에 포함되는 대기 신청을 찾아서 처리
    
    Returns:
        자동 예약이 성공한 경우 예약 정보, 실패한 경우 None
    """
    from reservation_db import _parse_time, _is_time_overlap
    
    # 취소된 예약 시간 파싱
    try:
        cancelled_start = _parse_time(start_time)
        cancelled_end = _parse_time(end_time)
    except ValueError:
        return None
    
    # 해당 강의실, 날짜의 모든 대기 신청 중에서
    # 취소된 예약 시간이 대기 신청의 시간 범위 안에 포함되는 것들을 찾기
    matching_entries = []
    for entry_id, entry in WAITLIST.items():
        if (entry["classroom_id"] == classroom_id and 
            entry["date"] == date):
            try:
                entry_start = _parse_time(entry["start_time"])
                entry_end = _parse_time(entry["end_time"])
                
                # 취소된 예약 시간이 대기 신청의 시간 범위 안에 포함되는지 확인
                # 또는 시간이 겹치는지 확인
                if _is_time_overlap(cancelled_start, cancelled_end, entry_start, entry_end):
                    matching_entries.append({**entry, "id": entry_id})
            except ValueError:
                continue
    
    # 우선순위와 생성 시간 순으로 정렬
    matching_entries.sort(key=lambda e: (e["priority"], e["created_at"]))
    
    if not matching_entries:
        return None
    
    # 대기 1순위부터 처리
    for entry in matching_entries:
        user_id = entry["user_id"]
        
        # 사용자의 현재 예약 개수 확인
        from reservation_db import count_active_reservations, create_reservation
        
        active_count = count_active_reservations(user_id)
        
        if active_count >= 3:
            # 예약이 3개면 대기 신청 삭제하고 다음 사용자로
            cancel_waitlist_entry(entry["id"], user_id)
            continue
        
        # 사용자가 설정한 전체 시간 범위로 예약 생성 시도
        entry_start_time = entry["start_time"]
        entry_end_time = entry["end_time"]
        
        success, message = create_reservation(
            user_id,
            classroom_id,
            date,
            entry_start_time,
            entry_end_time
        )
        
        if success:
            # 대기 신청 삭제
            del WAITLIST[entry["id"]]
            
            # 같은 시간 범위의 다른 대기 신청들의 우선순위 재정렬
            for other_entry in WAITLIST.values():
                if (other_entry["classroom_id"] == classroom_id and
                    other_entry["date"] == date and
                    other_entry["start_time"] == entry_start_time and
                    other_entry["end_time"] == entry_end_time):
                    priority = sum(1 for e in WAITLIST.values()
                                  if (e["classroom_id"] == classroom_id and
                                      e["date"] == date and
                                      e["start_time"] == entry_start_time and
                                      e["end_time"] == entry_end_time and
                                      e["created_at"] < other_entry["created_at"]))
                    other_entry["priority"] = priority
            
            _save_waitlist()
            
            # 알림 생성
            from notification_db import create_notification
            from classroom_db import get_classroom
            
            classroom = get_classroom(classroom_id)
            classroom_name = classroom["name"] if classroom else f"강의실 {classroom_id}"
            notification_message = f"[{classroom_name}] 대기 신청하신 예약이 자동으로 할당되었습니다. ({date} {entry_start_time}~{entry_end_time})"
            
            from reservation_db import RESERVATIONS
            reservation_id = max(RESERVATIONS.keys()) if RESERVATIONS else None
            if reservation_id:
                create_notification(user_id, reservation_id, notification_message)
            
            return {
                "user_id": user_id,
                "classroom_id": classroom_id,
                "date": date,
                "start_time": entry_start_time,
                "end_time": entry_end_time
            }
    
    return None

