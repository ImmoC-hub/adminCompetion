import json
import os
from typing import Optional

# 강의실 데이터 저장소
# 구조: {classroom_id: {"name": str, "location": str, "capacity": int, "equipment": dict}}
CLASSROOMS_FILE = "classrooms.json"
CLASSROOMS: dict[int, dict] = {}
_next_id = 1

def _load_classrooms() -> tuple[dict[int, dict], int]:
    """파일에서 강의실 데이터 로드"""
    if os.path.exists(CLASSROOMS_FILE):
        try:
            with open(CLASSROOMS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # JSON에서는 키가 문자열이므로 정수로 변환
                classrooms = {int(k): v for k, v in data.get("classrooms", {}).items()}
                next_id = data.get("next_id", 1)
                return classrooms, next_id
        except (json.JSONDecodeError, IOError, ValueError, KeyError):
            return {}, 1
    return {}, 1

def _save_classrooms() -> None:
    """강의실 데이터를 파일에 저장"""
    try:
        # JSON에서는 키가 문자열이므로 변환
        data = {
            "classrooms": {str(k): v for k, v in CLASSROOMS.items()},
            "next_id": _next_id
        }
        with open(CLASSROOMS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except IOError:
        pass  # 파일 저장 실패 시 무시 (로깅 가능)

# 서버 시작 시 데이터 로드
loaded_classrooms, loaded_next_id = _load_classrooms()
CLASSROOMS.update(loaded_classrooms)
_next_id = loaded_next_id

def create_classroom(name: str, location: str, capacity: int, equipment: Optional[dict] = None) -> int:
    """강의실을 생성하고 ID를 반환"""
    global _next_id
    classroom_id = _next_id
    _next_id += 1
    
    CLASSROOMS[classroom_id] = {
        "name": name,
        "location": location,
        "capacity": capacity,
        "equipment": equipment or {}
    }
    _save_classrooms()  # 파일에 저장
    return classroom_id

def get_classroom(classroom_id: int) -> Optional[dict]:
    """강의실 정보를 조회"""
    return CLASSROOMS.get(classroom_id)

def get_all_classrooms() -> dict[int, dict]:
    """모든 강의실 정보를 조회"""
    return CLASSROOMS.copy()

def update_classroom(classroom_id: int, name: Optional[str] = None, 
                     location: Optional[str] = None, capacity: Optional[int] = None,
                     equipment: Optional[dict] = None) -> bool:
    """강의실 정보를 수정"""
    if classroom_id not in CLASSROOMS:
        return False
    
    if name is not None:
        CLASSROOMS[classroom_id]["name"] = name
    if location is not None:
        CLASSROOMS[classroom_id]["location"] = location
    if capacity is not None:
        CLASSROOMS[classroom_id]["capacity"] = capacity
    if equipment is not None:
        CLASSROOMS[classroom_id]["equipment"] = equipment
    
    _save_classrooms()  # 파일에 저장
    return True

def delete_classroom(classroom_id: int) -> bool:
    """강의실을 삭제"""
    if classroom_id in CLASSROOMS:
        del CLASSROOMS[classroom_id]
        _save_classrooms()  # 파일에 저장
        return True
    return False

