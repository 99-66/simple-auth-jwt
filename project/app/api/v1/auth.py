from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, status, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.crud_token import RefreshTokenDAL
from db.crud.crud_user import UserDAL
from app.core.auth import authenticate, create_new_jwt_token
from dependencies.auth import AuthorizeCookieUser, AuthorizeTokenUser, credentials_exception, AuthorizeTokenRefresh, \
    AuthorizeRefreshCookieUser
from dependencies.database import get_session
from internal.config import settings
from internal.logging import app_logger
from schemas.auth import LoginRequestSchema
from app.core.security.encryption import AESCipher, Hasher
from schemas.token import CreateTokenSchema, InsertTokenSchema, TokenUser, UpdateTokenSchema, TokenSchema

router = APIRouter(prefix='/v1/auth', tags=['auth'])


@router.post('/api/login', response_model=CreateTokenSchema)
async def api_login(*,
                    request: Request,
                    login_info: LoginRequestSchema,
                    session: AsyncSession = Depends(get_session)):
    """
    User Login API(API Version)

    로그인 정보로 인증 처리 후에 JWT Token을 반환한다

    Login Process
        1. 사용자 인증 정보 확인
        2. AccessToken과 RefreshToken을 쌍으로 발급한다(AccessToken은 10분, RefreshToken은 7일의 만료 시간을 갖는다)
        3. RefreshToken은 `token` 테이블에 저장한다: token 값은 암호화해서 저장한다
    """

    # AES Encryption Instance
    aes = AESCipher()

    # Database Instance
    user_dal = UserDAL(session=session)
    r_token_dal = RefreshTokenDAL(session=session)

    # 암호화된 이메일 검색을 위한 blind index 생성
    email_key = Hasher.hmac_sha256(login_info.email)
    # 사용자 이메일이 존재하는지 확인한다
    user = await user_dal.get_user_from_email(email_key)

    # 로그인 인증
    is_login = await authenticate(user, login_info.password)
    if not is_login:
        return JSONResponse({'message': 'Incorrect username or password.'},
                            status_code=status.HTTP_401_UNAUTHORIZED)

    # JWT Token 발급
    token = await create_new_jwt_token(sub=str(user.id))
    # refreshToken insert schema 생성
    insert_refresh_token = InsertTokenSchema(user_id=user.id,
                                             access_token=token.access_token,
                                             refresh_token=aes.encrypt(token.refresh_token),
                                             refresh_token_key=Hasher.hmac_sha256(token.refresh_token),
                                             issued_at=datetime.fromtimestamp(int(token.iat)),
                                             expires_at=datetime.fromtimestamp(int(token.refresh_token_expires_in)))

    try:
        # RefreshToken을 저장한다
        await r_token_dal.insert(insert_refresh_token)
        # 마지막 로그인 정보를 업데이트한다
        await user_dal.update_last_login(user_id=user.id, login_ip=request.client.host)

        await session.commit()
    except Exception as e:
        app_logger.error(e)
        await session.rollback()
        return JSONResponse({'message': 'Failed to select/insert data'},
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        await session.close()

    return token


@router.post('/web/login')
async def web_login(*,
                    request: Request,
                    login_info: LoginRequestSchema,
                    session: AsyncSession = Depends(get_session)):
    """
    User Login API(Web Version)

    로그인 정보로 인증 처리 후에 JWT Token을 cookie(httpOnly)에 넣어서 반환한다

    Login Process
        1. 사용자 인증 정보 확인
        2. AccessToken과 RefreshToken을 쌍으로 발급한다(AccessToken은 10분, RefreshToken은 7일의 만료 시간을 갖는다)
        3. RefreshToken은 `token` 테이블에 저장한다: token 값은 암호화해서 저장한다
    """

    # AES Encryption Instance
    aes = AESCipher()

    # Database Instance
    user_dal = UserDAL(session=session)
    r_token_dal = RefreshTokenDAL(session=session)

    # 암호화된 이메일 검색을 위한 blind index 생성
    email_key = Hasher.hmac_sha256(login_info.email)
    # 사용자 이메일이 존재하는지 확인한다
    user = await user_dal.get_user_from_email(email_key)

    # 로그인 인증
    is_login = await authenticate(user, login_info.password)
    if not is_login:
        return JSONResponse({'message': 'Incorrect username or password.'},
                            status_code=status.HTTP_401_UNAUTHORIZED)

    # JWT Token 발급
    token = await create_new_jwt_token(sub=str(user.id))
    # refreshToken insert schema 생성
    insert_refresh_token = InsertTokenSchema(user_id=user.id,
                                             access_token=token.access_token,
                                             refresh_token=aes.encrypt(token.refresh_token),
                                             refresh_token_key=Hasher.hmac_sha256(token.refresh_token),
                                             issued_at=datetime.fromtimestamp(int(token.iat)),
                                             expires_at=datetime.fromtimestamp(int(token.refresh_token_expires_in)))

    try:
        # RefreshToken을 저장한다
        await r_token_dal.insert(insert_refresh_token)
        # 마지막 로그인 정보를 업데이트한다
        await user_dal.update_last_login(user_id=user.id, login_ip=request.client.host)

        await session.commit()
    except Exception as e:
        app_logger.error(e)
        await session.rollback()
        return JSONResponse({'message': 'Failed to select/insert data'},
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        await session.close()

    response = JSONResponse({'message': 'login success'})
    response.set_cookie(key='access_token', value=f'{token.access_token}', httponly=True)
    response.set_cookie(key='refresh_token', value=f'{token.refresh_token}', httponly=True)

    return response


@router.post('/api/logout')
async def api_logout(*,
                     token: TokenUser = Depends(AuthorizeTokenUser()),
                     session: AsyncSession = Depends(get_session)):
    """
    User Logout API(API Version)

    Logout Process
        1. RefreshToken을 `token` 테이블에서 삭제한다
    """

    token_dal = RefreshTokenDAL(session=session)

    try:
        # refreshToken이 존재하는지 확인한 후 삭제한다
        if await token_dal.exists(user_id=int(token.sub),
                                  access_token=token.access_token):
            await token_dal.delete(user_id=int(token.sub),
                                   access_token=token.access_token)

            await session.commit()
        else:
            raise Exception('user token not found')
    except ValueError as e:
        await session.rollback()
        return JSONResponse({'message': str(e)},
                            status_code=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        app_logger.error(e)
        await session.rollback()
        return JSONResponse({'message': 'Invalid Refresh Token'},
                            status_code=status.HTTP_404_NOT_FOUND)
    finally:
        await session.close()

    return JSONResponse({'message': 'logout success'})


@router.post('/web/logout')
async def web_logout(*,
                     token: TokenUser = Depends(AuthorizeCookieUser()),
                     session: AsyncSession = Depends(get_session)):
    """
    User Logout API(Web Version)

    Logout Process
        1. accessToken 유효성 확인
        2. RefreshToken을 `token` 테이블에서 삭제한다
        3. cookie에서 토큰을 삭제한다
    """
    token_dal = RefreshTokenDAL(session=session)

    try:
        # refreshToken이 존재하는지 확인한 후 삭제한다
        if await token_dal.exists(user_id=int(token.sub),
                                  access_token=token.access_token):
            await token_dal.delete(user_id=int(token.sub),
                                   access_token=token.access_token)

            await session.commit()
        else:
            raise ValueError('user token not found')
    except ValueError as e:
        await session.rollback()
        return JSONResponse({'message': str(e)},
                            status_code=status.HTTP_404_NOT_FOUND)

    except Exception as e:
        app_logger.error(e)
        await session.rollback()
        return JSONResponse({'message': 'Token Expired fail'},
                            status_code=status.HTTP_404_NOT_FOUND)
    else:
        # Cookie에 accessToken과 refreshToken을 삭제한다
        response = JSONResponse({'message': 'logout success'})
        response.set_cookie(key='access_token', value='', httponly=True, max_age=0)
        response.set_cookie(key='refresh_token', value='', httponly=True, max_age=0)

        return response
    finally:
        await session.close()


@router.post('/api/token/refresh', response_model=TokenSchema)
async def api_token_refresh(*,
                            token: TokenUser = Depends(AuthorizeTokenRefresh()),
                            session: AsyncSession = Depends(get_session)):
    """
    JWT Token Refresh API(API Version)

    Refresh Process
        1. DB에서 refreshToken을 가져온다
        2. DB에 저장된 refreshToken과 요청한 refreshToken을 비교
        3. accessToken / refreshToken 신규 발급
        4. DB에 refreshToken 정보 업데이트
    """

    # AES Encryption Instance
    aes = AESCipher()

    # Database Instance
    token_dal = RefreshTokenDAL(session=session)

    token_info = await token_dal.get(user_id=int(token.sub), access_token=token.access_token)

    if not token_info or token.refresh_token != aes.decrypt(token_info.refresh_token):
        raise credentials_exception

    # 신규 JWT Token 발급
    new_token = await create_new_jwt_token(sub=token.sub)

    # refreshToken 유효 사간이 'jwt_access_token_expire_minutes' 보다 적게 남은 경우에만 새로운 token을 반환한다
    # 그렇지 않은 경우에는 새로 생성한 refreshToken을 저장하지 않는다
    # Think: 리팩토링의 여지가 남았다. refreshToken의 생성 여부를 결정하는게 아니라 일단 생성한 후에 신규 token의 사용 여부를 결정한다
    # remain_expire_at: timedelta = token_info.expires_at - datetime.now()
    # if int(remain_expire_at.total_seconds() // 60) > settings.jwt_access_token_expire_minutes:
    #     new_token.refresh_token = aes.decrypt(token_info.refresh_token)
    #     new_token.refresh_token_expires_in = str(int(token_info.expires_at.timestamp()))

    # refreshToken update schema 생성
    update_token = UpdateTokenSchema(user_id=int(token.sub),
                                     old_access_token=token.access_token,
                                     new_access_token=new_token.access_token,
                                     refresh_token_key=Hasher.hmac_sha256(new_token.refresh_token),
                                     refresh_token=aes.encrypt(new_token.refresh_token),
                                     expires_at=datetime.fromtimestamp(int(new_token.refresh_token_expires_in)))

    try:
        await token_dal.update(update_token)

        await session.commit()
    except Exception as e:
        app_logger.error(e)
        await session.rollback()
        return JSONResponse({'message': 'Token Update failed'},
                            status_code=status.HTTP_404_NOT_FOUND)
    finally:
        await session.close()

    return TokenSchema(access_token=new_token.access_token,
                       refresh_token=new_token.refresh_token)


@router.post('/web/token/refresh')
async def web_token_refresh(*,
                            token: TokenUser = Depends(AuthorizeRefreshCookieUser()),
                            session: AsyncSession = Depends(get_session)):
    """
    JWT Token Refresh API(Web Version)

    Refresh Process
        1. DB에서 refreshToken을 가져온다
        2. DB에 저장된 refreshToken과 요청한 refreshToken을 비교
        3. accessToken / refreshToken 신규 발급
        4. DB에 refreshToken 정보 업데이트
    """

    # AES Encryption Instance
    aes = AESCipher()

    # Database Instance
    token_dal = RefreshTokenDAL(session=session)

    token_info = await token_dal.get(user_id=int(token.sub), access_token=token.access_token)
    if not token_info or token.refresh_token != aes.decrypt(token_info.refresh_token):
        raise credentials_exception

    # 신규 JWT Token 발급
    new_token = await create_new_jwt_token(sub=token.sub)

    # refreshToken 유효 사간이 'jwt_access_token_expire_minutes' 보다 적게 남은 경우에만 새로운 token을 반환한다
    # 그렇지 않은 경우에는 새로 생성한 refreshToken을 저장하지 않는다
    # Think: 리팩토링의 여지가 남았다. refreshToken의 생성 여부를 결정하는게 아니라 일단 생성한 후에 신규 token의 사용 여부를 결정한다
    # remain_expire_at: timedelta = token_info.expires_at - datetime.now()
    # if int(remain_expire_at.total_seconds() // 60) > settings.jwt_access_token_expire_minutes:
    #     new_token.refresh_token = aes.decrypt(token_info.refresh_token)
    #     new_token.refresh_token_expires_in = str(int(token_info.expires_at.timestamp()))

    # refreshToken update schema 생성
    update_token = UpdateTokenSchema(user_id=int(token.sub),
                                     old_access_token=token.access_token,
                                     new_access_token=new_token.access_token,
                                     refresh_token_key=Hasher.hmac_sha256(new_token.refresh_token),
                                     refresh_token=aes.encrypt(new_token.refresh_token),
                                     expires_at=datetime.fromtimestamp(int(new_token.refresh_token_expires_in)))

    try:
        await token_dal.update(update_token)

        await session.commit()
    except Exception as e:
        app_logger.error(e)
        await session.rollback()
        return JSONResponse({'message': 'Token Update failed'},
                            status_code=status.HTTP_404_NOT_FOUND)
    else:
        # Cookie에 accessToken을 업데이트한다
        response = JSONResponse({'message': 'refresh success'})
        response.set_cookie(key='access_token', value=f'{new_token.access_token}', httponly=True)
        response.set_cookie(key='refresh_token', value=f'{new_token.refresh_token}', httponly=True)

        return response
    finally:
        await session.close()

