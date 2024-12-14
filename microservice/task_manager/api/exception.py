from fastapi import HTTPException, status as Status

class UnauthorizedException(HTTPException):
    def __init__(self, detail: str = "Not authorized"):
        super().__init__(
            status_code=Status.HTTP_401_UNAUTHORIZED,
            detail=detail
        )

class NotFoundException(HTTPException):
    def __init__(self, detail: str = "Not Found"):
        super().__init__(
            status_code=Status.HTTP_404_NOT_FOUND,
            detail=detail,
        )