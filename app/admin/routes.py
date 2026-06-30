from fastapi import APIRouter, Request, Form, Depends, Response, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.db.session import get_db
from app.db.models import AdminUser, Conversation, Message, Rule, Product, Order, Ticket
from app.admin.auth import verify_password, create_access_token, hash_password
from app.admin.deps import get_current_admin, require_superadmin

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")


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
    conv_count = (await db.execute(select(Conversation))).scalars().all()
    ticket_count = (await db.execute(select(Ticket).where(Ticket.status == "open"))).scalars().all()
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
    result = await db.execute(select(Conversation).order_by(desc(Conversation.created_at)).limit(50))
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
    current_user: AdminUser = Depends(get_current_admin),
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
    current_user: AdminUser = Depends(get_current_admin),
):
    db.add(Rule(name=name, trigger=trigger, body=body, priority=priority))
    await db.commit()
    return RedirectResponse(url="/admin/rules", status_code=302)


@router.post("/rules/{rule_id}/delete")
async def delete_rule(
    rule_id: int, db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
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
):
    result = await db.execute(select(Product))
    products = result.scalars().all()
    return templates.TemplateResponse(
        request=request, name="admin/products.html",
        context={"current_user": current_user, "products": products},
    )


@router.post("/products")
async def create_product(
    request: Request,
    name: str = Form(...), sku: str = Form(...),
    price_cny: float = Form(...), price_xaf: float = Form(...),
    duty_rate: float = Form(0.30), vat_rate: float = Form(0.1925),
    weight_kg: float = Form(None), stock: int = Form(0),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    db.add(Product(
        name=name, sku=sku.upper(), price_cny=price_cny, price_xaf=price_xaf,
        duty_rate=duty_rate, vat_rate=vat_rate, weight_kg=weight_kg, stock=stock,
    ))
    await db.commit()
    return RedirectResponse(url="/admin/products", status_code=302)


@router.post("/products/{product_id}/delete")
async def delete_product(
    product_id: int, db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if product:
        await db.delete(product)
        await db.commit()
    return RedirectResponse(url="/admin/products", status_code=302)


@router.get("/orders", response_class=HTMLResponse)
async def orders_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    result = await db.execute(select(Order).order_by(desc(Order.created_at)))
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
        order.status = status
        await db.commit()
    return RedirectResponse(url="/admin/orders", status_code=302)


@router.get("/tickets", response_class=HTMLResponse)
async def tickets_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    result = await db.execute(select(Ticket).order_by(desc(Ticket.created_at)))
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
    current_user: AdminUser = Depends(require_superadmin),
):
    from app.worker import export_conversations_csv
    export_conversations_csv()
    return RedirectResponse(url="/admin/reports", status_code=302)
