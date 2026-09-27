from fastapi import HTTPException


def session_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail={
        "code": "SESSION_NOT_FOUND", "message": "Session does not exist."
    })
