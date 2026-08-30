from fastapi import APIRouter, Request, Form, Depends, Response, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, or_
from sqlalchemy.orm import selectinload
from app.db.session import get_db
from app.db.models import AdminUser, Conversation, Message, Rule, Product, ProductImage, Order, Ticket
from app.admin.auth import verify_password, create_access_token, hash_password
from app.admin.deps import get_current_admin, require_superadmin, scope_clause, assert_visible
from app.countries import normalize_country
from app.media import media_url, save_upload

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")
templates.env.globals["media_url"] = media_url

PRODUCT_CATEGORIES = ["solar_panels", "batteries", "inverters", "charge_controllers", "ess", "other"]


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="admin/login.html", context={"error": None})


@router.post("/login")
async def login(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AdminUser).where(AdminUser.email == email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request=request,
            name="admin/login.html",
            context={"error": "Invalid email or password"},
            status_code=401,
        )
    token = create_access_token({"sub": str(user.id), "role": user.role})
    resp = RedirectResponse(url="/admin/dashboard", status_code=302)
    resp.set_cookie("admin_token", token, httponly=True, samesite="lax")
    return resp


@router.post("/logout")
async def logout():
    resp = RedirectResponse(url="/admin/login", status_code=302)
    resp.delete_cookie("admin_token")
    return resp


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    conv_count = (await db.execute(
        select(Conversation).where(scope_clause(current_user, Conversation))
    )).scalars().all()
    open_tickets_stmt = select(Ticket).where(Ticket.status == "open")
    if current_user.country is not None:
        open_tickets_stmt = (
            select(Ticket)
            .join(Conversation, Ticket.conversation_id == Conversation.id)
            .where(Ticket.status == "open", Conversation.country == current_user.country)
        )
    ticket_count = (await db.execute(open_tickets_stmt)).scalars().all()
    return templates.TemplateResponse(
        request=request, name="admin/dashboard.html",
        context={"current_user": current_user, "conv_count": len(conv_count), "open_tickets": len(ticket_count)},
    )


@router.get("/conversations", response_class=HTMLResponse)
async def conversations(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    result = await db.execute(
        select(Conversation)
        .where(scope_clause(current_user, Conversation))
        .order_by(desc(Conversation.created_at)).limit(50)
    )
    convs = result.scalars().all()
    return templates.TemplateResponse(
        request=request, name="admin/conversations.html",
        context={"current_user": current_user, "conversations": convs},
    )


@router.get("/conversations/{conv_id}", response_class=HTMLResponse)
async def conversation_detail(
    conv_id: int, request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    assert_visible(current_user, conv)
    msg_result = await db.execute(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at)
    )
    msgs = msg_result.scalars().all()
    return templates.TemplateResponse(
        request=request, name="admin/conversation_detail.html",
        context={"current_user": current_user, "conversation": conv, "messages": msgs},
    )


@router.get("/rules", response_class=HTMLResponse)
async def rules_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_superadmin),
):
    result = await db.execute(select(Rule).order_by(Rule.priority))
    rules = result.scalars().all()
    return templates.TemplateResponse(
        request=request, name="admin/rules.html",
        context={"current_user": current_user, "rules": rules},
    )


@router.post("/rules", response_class=HTMLResponse)
async def create_rule(
    request: Request,
    name: str = Form(...), trigger: str = Form(""), body: str = Form(...), priority: int = Form(10),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_superadmin),
):
    db.add(Rule(name=name, trigger=trigger, body=body, priority=priority))
    await db.commit()
    return RedirectResponse(url="/admin/rules", status_code=302)


@router.post("/rules/{rule_id}/delete")
async def delete_rule(
    rule_id: int, db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_superadmin),
):
    result = await db.execute(select(Rule).where(Rule.id == rule_id))
    rule = result.scalar_one_or_none()
    if rule:
        await db.delete(rule)
        await db.commit()
    return RedirectResponse(url="/admin/rules", status_code=302)


@router.get("/products", response_class=HTMLResponse)
async def products_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
    category: str | None = None,
):
    stmt = select(Product).options(selectinload(Product.images)).order_by(Product.category, Product.sku)
    if current_user.country is not None:
        stmt = stmt.where(or_(Product.country.is_(None), Product.country == current_user.country))
    if category:
        stmt = stmt.where(Product.category == category)
    result = await db.execute(stmt)
    products = result.scalars().all()

    total_count = await db.scalar(select(func.count()).select_from(Product))

    cats_result = await db.execute(select(Product.category).distinct())
    categories = sorted(c for (c,) in cats_result.all() if c)

    return templates.TemplateResponse(
        request=request, name="admin/products.html",
        context={
            "current_user": current_user, "products": products, "total_count": total_count,
            "categories": categories, "selected_category": category,
            "category_choices": PRODUCT_CATEGORIES,
        },
    )


def _product_fields_from_form(
    name, sku, category, subcategory, model, wattage, power_kw, capacity_ah,
    capacity_kwh, voltage, dimensions, price_cny, price_xaf, duty_rate, vat_rate,
    weight_kg, stock, featured, features, use_cases,
) -> dict:
    return dict(
        name=name, sku=sku.upper(), category=category or None, subcategory=subcategory or None,
        model=model or None, wattage=wattage or None, power_kw=power_kw or None,
        capacity_ah=capacity_ah or None, capacity_kwh=capacity_kwh or None, voltage=voltage or None,
        dimensions=dimensions or None, price_cny=price_cny, price_xaf=price_xaf,
        duty_rate=duty_rate, vat_rate=vat_rate, weight_kg=weight_kg, stock=stock,
        featured=featured, features=features or None, use_cases=use_cases or None,
    )


def _assert_product_writable(current_user: AdminUser, product: Product) -> None:
    if current_user.country is not None and product.country is None:
        raise HTTPException(status_code=403, detail="Shared catalog is superadmin-only")
    assert_visible(current_user, product)


@router.post("/products")
async def create_product(
    request: Request,
    name: str = Form(...), sku: str = Form(...), country: str = Form(None),
    category: str = Form(None), subcategory: str = Form(None), model: str = Form(None),
    wattage: str = Form(None), power_kw: str = Form(None), capacity_ah: str = Form(None),
    capacity_kwh: str = Form(None), voltage: str = Form(None), dimensions: str = Form(None),
    price_cny: float = Form(None), price_xaf: float = Form(None),
    duty_rate: float = Form(0.30), vat_rate: float = Form(0.1925),
    weight_kg: float = Form(None), stock: int = Form(0),
    featured: bool = Form(False), features: str = Form(None), use_cases: str = Form(None),
    datasheet: UploadFile = File(None), primary_image: UploadFile = File(None),
    gallery_images: list[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    fields = _product_fields_from_form(
        name, sku, category, subcategory, model, wattage, power_kw, capacity_ah,
        capacity_kwh, voltage, dimensions, price_cny, price_xaf, duty_rate, vat_rate,
        weight_kg, stock, featured, features, use_cases,
    )
    product = Product(**fields)
    if current_user.country is not None:
        product.country = current_user.country
    elif country:
        product.country = normalize_country(country)

    if datasheet and datasheet.filename:
        product.datasheet_asset_id = await save_upload(db, datasheet, "datasheet")
    if primary_image and primary_image.filename:
        product.image_asset_id = await save_upload(db, primary_image, "image")

    db.add(product)
    await db.flush()

    for i, img in enumerate([g for g in (gallery_images or []) if g and g.filename]):
        asset_id = await save_upload(db, img, "image")
        db.add(ProductImage(product_id=product.id, path="", asset_id=asset_id, sort_order=i))

    await db.commit()
    return RedirectResponse(url="/admin/products", status_code=302)


@router.get("/products/{product_id}/edit", response_class=HTMLResponse)
async def edit_product_page(
    product_id: int, request: Request, db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    result = await db.execute(
        select(Product).options(selectinload(Product.images)).where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    _assert_product_writable(current_user, product)
    return templates.TemplateResponse(
        request=request, name="admin/product_edit.html",
        context={"current_user": current_user, "p": product, "category_choices": PRODUCT_CATEGORIES},
    )


@router.post("/products/{product_id}/edit")
async def update_product(
    product_id: int, request: Request,
    name: str = Form(...), sku: str = Form(...),
    category: str = Form(None), subcategory: str = Form(None), model: str = Form(None),
    wattage: str = Form(None), power_kw: str = Form(None), capacity_ah: str = Form(None),
    capacity_kwh: str = Form(None), voltage: str = Form(None), dimensions: str = Form(None),
    price_cny: float = Form(None), price_xaf: float = Form(None),
    duty_rate: float = Form(0.30), vat_rate: float = Form(0.1925),
    weight_kg: float = Form(None), stock: int = Form(0),
    featured: bool = Form(False), features: str = Form(None), use_cases: str = Form(None),
    datasheet: UploadFile = File(None), primary_image: UploadFile = File(None),
    gallery_images: list[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    result = await db.execute(
        select(Product).options(selectinload(Product.images)).where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    _assert_product_writable(current_user, product)

    fields = _product_fields_from_form(
        name, sku, category, subcategory, model, wattage, power_kw, capacity_ah,
        capacity_kwh, voltage, dimensions, price_cny, price_xaf, duty_rate, vat_rate,
        weight_kg, stock, featured, features, use_cases,
    )
    for key, value in fields.items():
        setattr(product, key, value)

    if datasheet and datasheet.filename:
        product.datasheet_asset_id = await save_upload(db, datasheet, "datasheet")
    if primary_image and primary_image.filename:
        product.image_asset_id = await save_upload(db, primary_image, "image")

    existing_count = len(product.images)
    for i, img in enumerate([g for g in (gallery_images or []) if g and g.filename]):
        asset_id = await save_upload(db, img, "image")
        db.add(ProductImage(
            product_id=product.id, path="", asset_id=asset_id, sort_order=existing_count + i,
        ))

    await db.commit()
    return RedirectResponse(url="/admin/products", status_code=302)


@router.post("/products/{product_id}/images/{image_id}/delete")
async def delete_product_image(
    product_id: int, image_id: int, db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    result = await db.execute(
        select(ProductImage).where(ProductImage.id == image_id, ProductImage.product_id == product_id)
    )
    image = result.scalar_one_or_none()
    if image:
        product = (await db.execute(
            select(Product).where(Product.id == product_id)
        )).scalar_one_or_none()
        if product:
            _assert_product_writable(current_user, product)
        await db.delete(image)
        await db.commit()
    return RedirectResponse(url=f"/admin/products/{product_id}/edit", status_code=302)


@router.post("/products/{product_id}/delete")
async def delete_product(
    product_id: int, db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if product:
        _assert_product_writable(current_user, product)
        await db.delete(product)
        await db.commit()
    return RedirectResponse(url="/admin/products", status_code=302)


@router.get("/orders", response_class=HTMLResponse)
async def orders_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    result = await db.execute(
        select(Order).where(scope_clause(current_user, Order)).order_by(desc(Order.created_at))
    )
    orders = result.scalars().all()
    return templates.TemplateResponse(
        request=request, name="admin/orders.html",
        context={"current_user": current_user, "orders": orders},
    )


@router.post("/orders/{order_id}/status")
async def update_order_status(
    order_id: int, status: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if order:
        assert_visible(current_user, order)
        order.status = status
        await db.commit()
    return RedirectResponse(url="/admin/orders", status_code=302)


@router.get("/tickets", response_class=HTMLResponse)
async def tickets_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    stmt = select(Ticket).order_by(desc(Ticket.created_at))
    if current_user.country is not None:
        stmt = (
            select(Ticket)
            .join(Conversation, Ticket.conversation_id == Conversation.id)
            .where(Conversation.country == current_user.country)
            .order_by(desc(Ticket.created_at))
        )
    result = await db.execute(stmt)
    tickets = result.scalars().all()
    return templates.TemplateResponse(
        request=request, name="admin/tickets.html",
        context={"current_user": current_user, "tickets": tickets},
    )


@router.post("/tickets/{ticket_id}/close")
async def close_ticket(
    ticket_id: int, db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    result = await db.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if ticket:
        if current_user.country is not None:
            conv = (await db.execute(
                select(Conversation).where(Conversation.id == ticket.conversation_id)
            )).scalar_one_or_none()
            if conv is None or conv.country != current_user.country:
                raise HTTPException(status_code=404, detail="Not found")
        ticket.status = "closed"
        await db.commit()
    return RedirectResponse(url="/admin/tickets", status_code=302)


@router.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_superadmin),
):
    result = await db.execute(select(AdminUser))
    users = result.scalars().all()
    return templates.TemplateResponse(
        request=request, name="admin/users.html",
        context={"current_user": current_user, "users": users},
    )


@router.post("/users")
async def create_user(
    email: str = Form(...), password: str = Form(...), role: str = Form("agent"),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_superadmin),
):
    db.add(AdminUser(email=email, password_hash=hash_password(password), role=role))
    await db.commit()
    return RedirectResponse(url="/admin/users", status_code=302)


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(
    request: Request, current_user: AdminUser = Depends(require_superadmin),
):
    return templates.TemplateResponse(
        request=request, name="admin/reports.html",
        context={"current_user": current_user},
    )


@router.post("/reports/export")
async def trigger_export(
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_superadmin),
):
    from app.worker import export_conversations_csv
    await export_conversations_csv(db)
    return RedirectResponse(url="/admin/reports", status_code=302)
