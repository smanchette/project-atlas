from fastapi import APIRouter

from app.api.backup_routes import router as backup_router
from app.api.media_routes import router as media_router
from app.api.page_generation_routes import router as page_generation_router
from app.api.page_editor_routes import router as page_editor_router
from app.api.page_export_routes import router as page_export_router
from app.api.page_media_routes import router as page_media_router
from app.api.qa_routes import router as qa_router
from app.api.wordpress_routes import router as wordpress_router
from app.api.router_factory import build_crud_router
from app.models import Business, City, County, GeneratedPage, ImageMetadata, KnowledgeBlock, Service, Setting
from app.schemas.entities import (
    BusinessCreate,
    BusinessRead,
    BusinessUpdate,
    CityCreate,
    CityRead,
    CityUpdate,
    CountyCreate,
    CountyRead,
    CountyUpdate,
    GeneratedPageCreate,
    GeneratedPageRead,
    GeneratedPageUpdate,
    ImageMetadataCreate,
    ImageMetadataRead,
    ImageMetadataUpdate,
    KnowledgeBlockCreate,
    KnowledgeBlockRead,
    KnowledgeBlockUpdate,
    ServiceCreate,
    ServiceRead,
    ServiceUpdate,
    SettingCreate,
    SettingRead,
    SettingUpdate,
)

api_router = APIRouter()
api_router.include_router(backup_router)
api_router.include_router(media_router)
api_router.include_router(page_generation_router)
api_router.include_router(page_editor_router)
api_router.include_router(page_export_router)
api_router.include_router(page_media_router)
api_router.include_router(qa_router)
api_router.include_router(wordpress_router)

api_router.include_router(
    build_crud_router(
        model=Business,
        create_schema=BusinessCreate,
        read_schema=BusinessRead,
        update_schema=BusinessUpdate,
        prefix="/businesses",
        tags=["businesses"],
    )
)
api_router.include_router(
    build_crud_router(
        model=Service,
        create_schema=ServiceCreate,
        read_schema=ServiceRead,
        update_schema=ServiceUpdate,
        prefix="/services",
        tags=["services"],
    )
)
api_router.include_router(
    build_crud_router(
        model=County,
        create_schema=CountyCreate,
        read_schema=CountyRead,
        update_schema=CountyUpdate,
        prefix="/counties",
        tags=["counties"],
    )
)
api_router.include_router(
    build_crud_router(
        model=City,
        create_schema=CityCreate,
        read_schema=CityRead,
        update_schema=CityUpdate,
        prefix="/cities",
        tags=["cities"],
    )
)
api_router.include_router(
    build_crud_router(
        model=GeneratedPage,
        create_schema=GeneratedPageCreate,
        read_schema=GeneratedPageRead,
        update_schema=GeneratedPageUpdate,
        prefix="/generated-pages",
        tags=["generated pages"],
    )
)
api_router.include_router(
    build_crud_router(
        model=ImageMetadata,
        create_schema=ImageMetadataCreate,
        read_schema=ImageMetadataRead,
        update_schema=ImageMetadataUpdate,
        prefix="/image-metadata",
        tags=["image metadata"],
    )
)
api_router.include_router(
    build_crud_router(
        model=KnowledgeBlock,
        create_schema=KnowledgeBlockCreate,
        read_schema=KnowledgeBlockRead,
        update_schema=KnowledgeBlockUpdate,
        prefix="/knowledge-blocks",
        tags=["knowledge blocks"],
    )
)
api_router.include_router(
    build_crud_router(
        model=Setting,
        create_schema=SettingCreate,
        read_schema=SettingRead,
        update_schema=SettingUpdate,
        prefix="/settings",
        tags=["settings"],
    )
)
