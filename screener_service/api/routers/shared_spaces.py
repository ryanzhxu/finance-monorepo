from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from shared.models import (
    SharedSpaceLoginRequest,
    SharedSpaceSessionResponse,
    SharedWatchlistAddRequest,
    SharedWatchlistResponse,
)

from screener_service.core.shared_spaces import (
    COOKIE_NAME,
    SharedSpace,
    SharedSpaceNotFoundError,
    SharedSpaceStore,
    SharedSpaceUnavailableError,
    build_session_cookie,
    read_session_cookie,
    verify_passcode,
)

router = APIRouter(prefix="/shared-spaces", tags=["shared-spaces"])


def _shared_space_store(request: Request) -> SharedSpaceStore:
    store = getattr(request.app.state, "shared_space_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Shared watchlist is not configured",
        )
    return store


def _load_space(store: SharedSpaceStore, slug: str) -> SharedSpace:
    try:
        return store.get_space(slug)
    except SharedSpaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shared space not found") from exc
    except SharedSpaceUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


def _cookie_options(request: Request, slug: str, max_age: int) -> dict[str, object]:
    secure = request.url.scheme == "https"
    return {
        "httponly": True,
        "max_age": max_age,
        "path": f"/shared-spaces/{slug}",
        "samesite": "none" if secure else "lax",
        "secure": secure,
    }


def _authenticated_space(request: Request, slug: str) -> SharedSpace:
    store = _shared_space_store(request)
    space = _load_space(store, slug)
    cookie_value = request.cookies.get(COOKIE_NAME)
    resolved_slug = read_session_cookie(cookie_value, store.settings.session_secret)
    if resolved_slug != space.slug:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return space


@router.get("/{slug}/session", response_model=SharedSpaceSessionResponse)
async def shared_space_session(slug: str, request: Request) -> SharedSpaceSessionResponse:
    store = _shared_space_store(request)
    space = _load_space(store, slug)
    authenticated = read_session_cookie(
        request.cookies.get(COOKIE_NAME),
        store.settings.session_secret,
    ) == space.slug
    return SharedSpaceSessionResponse(
        authenticated=authenticated,
        slug=space.slug,
        display_name=space.display_name,
    )


@router.post("/{slug}/login", response_model=SharedSpaceSessionResponse)
async def shared_space_login(
    slug: str,
    payload: SharedSpaceLoginRequest,
    request: Request,
    response: Response,
) -> SharedSpaceSessionResponse:
    store = _shared_space_store(request)
    space = _load_space(store, slug)
    if not verify_passcode(payload.passcode, space.passcode_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid passcode")
    response.set_cookie(
        COOKIE_NAME,
        build_session_cookie(space.slug, store.settings.session_secret, store.settings.session_max_age),
        **_cookie_options(request, space.slug, store.settings.session_max_age),
    )
    return SharedSpaceSessionResponse(authenticated=True, slug=space.slug, display_name=space.display_name)


@router.post("/{slug}/logout", response_model=SharedSpaceSessionResponse)
async def shared_space_logout(slug: str, request: Request, response: Response) -> SharedSpaceSessionResponse:
    store = _shared_space_store(request)
    space = _load_space(store, slug)
    response.delete_cookie(COOKIE_NAME, path=f"/shared-spaces/{space.slug}")
    return SharedSpaceSessionResponse(authenticated=False, slug=space.slug, display_name=space.display_name)


@router.get("/{slug}/watchlist", response_model=SharedWatchlistResponse)
async def get_shared_watchlist(slug: str, request: Request) -> SharedWatchlistResponse:
    space = _authenticated_space(request, slug)
    store = _shared_space_store(request)
    symbols = store.list_symbols(space.slug)
    return SharedWatchlistResponse(slug=space.slug, display_name=space.display_name, symbols=symbols)


@router.post("/{slug}/watchlist", response_model=SharedWatchlistResponse)
async def add_shared_watchlist_symbol(
    slug: str,
    payload: SharedWatchlistAddRequest,
    request: Request,
) -> SharedWatchlistResponse:
    space = _authenticated_space(request, slug)
    store = _shared_space_store(request)
    symbols = store.add_symbol(space.slug, payload.symbol)
    return SharedWatchlistResponse(slug=space.slug, display_name=space.display_name, symbols=symbols)


@router.delete("/{slug}/watchlist/{symbol}", response_model=SharedWatchlistResponse)
async def remove_shared_watchlist_symbol(slug: str, symbol: str, request: Request) -> SharedWatchlistResponse:
    space = _authenticated_space(request, slug)
    store = _shared_space_store(request)
    symbols = store.remove_symbol(space.slug, symbol)
    return SharedWatchlistResponse(slug=space.slug, display_name=space.display_name, symbols=symbols)
