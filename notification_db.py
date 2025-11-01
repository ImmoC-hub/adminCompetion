import json
import os
from datetime import datetime, date, time, timedelta
from typing import Optional, List

# 알림 데이터 저장소
# 구조: {notification_id: {"user_id": str, "reservation_id": int, "message": str, "created_at": str, "read": bool}}
NOTIFICATIONS_FILE = "notifications.json"
NOTIFICATIONS: dict[int, dict] = {}
_next_id = 1

def _load_notifications() -> tuple[dict[int, dict], int]:
    """파일에서 알림 데이터 로드"""
    if os.path.exists(NOTIFICATIONS_FILE):
        try:
            with open(NOTIFICATIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                notifications = {int(k): v for k, v in data.get("notifications", {}).items()}
                next_id = data.get("next_id", 1)
                return notifications, next_id
        except (json.JSONDecodeError, IOError, ValueError, KeyError):
            return {}, 1
    return {}, 1

def _save_notifications() -> None:
    """알림 데이터를 파일에 저장"""
    try:
        data = {
            "notifications": {str(k): v for k, v in NOTIFICATIONS.items()},
            "next_id": _next_id
        }
        with open(NOTIFICATIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except IOError:
        pass

# 서버 시작 시 데이터 로드
loaded_notifications, loaded_next_id = _load_notifications()
NOTIFICATIONS.update(loaded_notifications)
_next_id = loaded_next_id

def create_notification(user_id: str, reservation_id: int, message: str) -> int:
    """알림 생성"""
    global _next_id
    notification_id = _next_id
    _next_id += 1
    
    NOTIFICATIONS[notification_id] = {
        "user_id": user_id,
        "reservation_id": reservation_id,
        "message": message,
        "created_at": datetime.now().isoformat(),
        "read": False
    }
    _save_notifications()
    return notification_id

def get_user_notifications(user_id: str, unread_only: bool = False) -> List[dict]:
    """사용자의 알림 목록 조회"""
    notifications = [
        {**notification, "id": notif_id}
        for notif_id, notification in NOTIFICATIONS.items()
        if notification["user_id"] == user_id
    ]
    
    if unread_only:
        notifications = [n for n in notifications if not n["read"]]
    
    # 최신순 정렬
    notifications.sort(key=lambda n: n["created_at"], reverse=True)
    return notifications

def mark_as_read(notification_id: int, user_id: str) -> bool:
    """알림을 읽음으로 표시"""
    if notification_id not in NOTIFICATIONS:
        return False
    
    notification = NOTIFICATIONS[notification_id]
    if notification["user_id"] != user_id:
        return False
    
    notification["read"] = True
    _save_notifications()
    return True

def mark_all_as_read(user_id: str) -> int:
    """사용자의 모든 알림을 읽음으로 표시"""
    count = 0
    for notification in NOTIFICATIONS.values():
        if notification["user_id"] == user_id and not notification["read"]:
            notification["read"] = True
            count += 1
    
    if count > 0:
        _save_notifications()
    return count

def get_unread_count(user_id: str) -> int:
    """사용자의 읽지 않은 알림 개수"""
    return sum(1 for n in NOTIFICATIONS.values() 
               if n["user_id"] == user_id and not n["read"])

def schedule_reservation_notification(reservation_id: int, user_id: str, 
                                     reservation_date: str, start_time_str: str,
                                     participants: List[str] = None) -> None:
    """예약 시간 시작 30분 전 알림 스케줄링"""
    from reservation_db import _parse_date, _parse_time
    
    try:
        reservation_date_obj = _parse_date(reservation_date)
        start_time_obj = _parse_time(start_time_str)
        
        # 예약 시작 시간
        reservation_datetime = datetime.combine(reservation_date_obj, start_time_obj)
        
        # 30분 전 시간
        notification_time = reservation_datetime - timedelta(minutes=30)
        
        # 과거 시간이면 알림 생성하지 않음
        if notification_time <= datetime.now():
            return
        
        # 예약자에게 알림 생성
        from classroom_db import get_classroom
        from reservation_db import get_reservation
        
        reservation = get_reservation(reservation_id)
        if not reservation:
            return
        
        classroom = get_classroom(reservation["classroom_id"])
        classroom_name = classroom["name"] if classroom else f"강의실 {reservation['classroom_id']}"
        
        message = f"[{classroom_name}] 예약이 {start_time_str}에 시작됩니다. (30분 전 알림)"
        create_notification(user_id, reservation_id, message)
        
        # 참여 인원에게도 알림 생성
        if participants:
            for participant_id in participants:
                from user_db import get_user
                if get_user(participant_id):  # 회원인 경우만
                    create_notification(participant_id, reservation_id, message)
    
    except (ValueError, TypeError):
        pass  # 날짜/시간 파싱 실패 시 무시

def check_and_create_notifications() -> None:
    """예약 시간 시작 30분 전인지 확인하고 알림 생성"""
    from reservation_db import RESERVATIONS, _parse_date, _parse_time
    
    now = datetime.now()
    notification_time = now + timedelta(minutes=30)
    
    for reservation_id, reservation in RESERVATIONS.items():
        try:
            reservation_date_obj = _parse_date(reservation["date"])
            start_time_obj = _parse_time(reservation["start_time"])
            reservation_datetime = datetime.combine(reservation_date_obj, start_time_obj)
            
            # 알림 시간과 예약 시작 시간이 일치하는지 확인 (5분 오차 허용)
            time_diff = abs((reservation_datetime - notification_time).total_seconds())
            
            if time_diff <= 300:  # 5분 이내
                # 이미 알림이 생성되었는지 확인
                user_id = reservation["user_id"]
                existing_notifications = get_user_notifications(user_id)
                
                notification_exists = any(
                    n["reservation_id"] == reservation_id and 
                    "30분 전 알림" in n["message"]
                    for n in existing_notifications
                )
                
                if not notification_exists:
                    from classroom_db import get_classroom
                    classroom = get_classroom(reservation["classroom_id"])
                    classroom_name = classroom["name"] if classroom else f"강의실 {reservation['classroom_id']}"
                    
                    message = f"[{classroom_name}] 예약이 {reservation['start_time']}에 시작됩니다. (30분 전 알림)"
                    create_notification(user_id, reservation_id, message)
                    
                    # 참여 인원에게도 알림
                    participants = reservation.get("participants", [])
                    for participant_id in participants:
                        from user_db import get_user
                        if get_user(participant_id):
                            create_notification(participant_id, reservation_id, message)
        except (ValueError, TypeError, KeyError):
            continue

