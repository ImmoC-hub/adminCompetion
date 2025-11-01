import json
import os
from typing import Literal

Role = Literal["Student", "Admin"]

USERS_FILE = "users.json"
USERS: dict[str, dict[str, str | Role]] = {}

def _load_users() -> dict[str, dict[str, str | Role]]:
    """파일에서 사용자 데이터 로드"""
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}

def _save_users() -> None:
    """사용자 데이터를 파일에 저장"""
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(USERS, f, ensure_ascii=False, indent=2)
    except IOError:
        pass  # 파일 저장 실패 시 무시 (로깅 가능)

# 서버 시작 시 데이터 로드
USERS.update(_load_users())

def register_user(user_id: str, password: str, role: Role) -> bool:
    """사용자를 등록하고 성공 여부를 반환"""
    if user_id in USERS:
        return False  # 이미 존재하는 ID
    USERS[user_id] = {
        "password": password,
        "role": role
    }
    _save_users()  # 파일에 저장
    return True

def get_user(user_id: str) -> dict[str, str | Role] | None:
    """사용자 ID로 사용자 정보를 조회"""
    return USERS.get(user_id)

def get_user_role(user_id: str) -> Role | None:
    """사용자 역할을 조회"""
    user = get_user(user_id)
    if user:
        return user.get("role")  # type: ignore
    return None