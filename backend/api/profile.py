"""学生档案（昵称 / 学校阶段 / 班级）与紧急联系人 API。

仅按匿名 student_ref 落库，不参与风险判定；持久化在
backend/data/student_profile.sqlite3，刷新 / 重启 / 重新打开页面后仍可读回。
"""

from fastapi import APIRouter, HTTPException, Path

from backend.core.profile_store import profile_store
from backend.models.profile import StudentProfile
from backend.models.requests import AddContactRequest, SaveProfileRequest
from backend.models.responses import (
    AddContactResponse,
    DeleteContactResponse,
    EmergencyContactListResponse,
    SaveProfileResponse,
)

# 档案与联系人分挂两个前缀：否则 /api/profile/{student_ref} 会把 "contacts"
# 当成 student_ref 吃掉，无法再挂 /api/profile/contacts。
router = APIRouter(prefix="/api/profile", tags=["profile"])
contacts_router = APIRouter(prefix="/api/contacts", tags=["contacts"])


@router.get("/{student_ref}", response_model=StudentProfile)
def get_profile(
    student_ref: str = Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
) -> StudentProfile:
    return profile_store.get_profile(student_ref)


@router.put("", response_model=SaveProfileResponse)
def save_profile(request: SaveProfileRequest) -> SaveProfileResponse:
    profile = profile_store.save_profile(
        request.student_ref, request.nickname, request.school_stage, request.class_name)
    return SaveProfileResponse(profile=profile)


@contacts_router.get("/{student_ref}", response_model=EmergencyContactListResponse)
def list_contacts(
    student_ref: str = Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
) -> EmergencyContactListResponse:
    return EmergencyContactListResponse(
        student_ref=student_ref, contacts=profile_store.list_contacts(student_ref))


@contacts_router.post("", response_model=AddContactResponse)
def add_contact(request: AddContactRequest) -> AddContactResponse:
    contact = profile_store.add_contact(
        request.student_ref, request.name, request.relation, request.phone)
    return AddContactResponse(contact=contact)


@contacts_router.delete("/{student_ref}/{contact_id}", response_model=DeleteContactResponse)
def remove_contact(
    student_ref: str = Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
    contact_id: str = Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
) -> DeleteContactResponse:
    if not profile_store.remove_contact(student_ref, contact_id):
        raise HTTPException(status_code=404, detail={
            "code": "CONTACT_NOT_FOUND", "message": "联系人不存在或已被删除。"})
    return DeleteContactResponse()
