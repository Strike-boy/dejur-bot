import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from services.duty_service import DutyService

log = logging.getLogger(__name__)


class IsAdmin(BaseFilter):
    def __init__(self, ids):
        self.ids = ids

    async def __call__(self, event, **kwargs) -> bool:
        user = getattr(event, "from_user", None)
        ok = bool(user and user.id in self.ids)
        if not ok and user:
            log.warning("Non-admin %s tried an admin action", user.id)
        return ok


ADMIN_HELP = (
    "Admin buyruqlari:\n"
    "/status - holat va navbat pozitsiyalari\n"
    "/preview - xabar ko'rinishi (navbat siljimaydi)\n"
    "/send - bugungi xabarni hozir yuborish\n"
    "/setgroup - guruhni belgilash (guruh ichida yoki /setgroup <chat_id>)\n"
    "/pause, /resume - avtomatik e'lonni to'xtatish/davom ettirish\n"
    "/reset - barcha navbatlarni boshiga qaytarish (tasdiq bilan)"
)


def build_admin_router(admin_ids) -> Router:
    r = Router()
    r.message.filter(IsAdmin(admin_ids))
    r.callback_query.filter(IsAdmin(admin_ids))

    @r.message(Command("admin"))
    async def admin(m: Message):
        await m.answer(ADMIN_HELP)

    @r.message(Command("status"))
    async def status(m: Message, service: DutyService):
        await m.answer(await service.status_text())

    @r.message(Command("preview"))
    async def preview(m: Message, service: DutyService):
        await m.answer("PREVIEW (navbat siljimadi):\n\n" + await service.preview_text())

    @r.message(Command("pause"))
    async def pause(m: Message, service: DutyService):
        await service.set_paused(True)
        await m.answer("Avtomatik e'lon to'xtatildi.")

    @r.message(Command("resume"))
    async def resume(m: Message, service: DutyService):
        await service.set_paused(False)
        await m.answer("Avtomatik e'lon davom ettirildi.")

    @r.message(Command("setgroup"))
    async def setgroup(m: Message, command: CommandObject, service: DutyService, bot: Bot):
        if command.args:
            try:
                chat_id = int(command.args.strip())
            except ValueError:
                return await m.answer("Noto'g'ri chat_id. Misol: /setgroup -1001234567890")
        elif m.chat.type != "private":
            chat_id = m.chat.id
        else:
            return await m.answer("Guruh ichida /setgroup yuboring yoki /setgroup <chat_id>.")
        try:
            chat = await bot.get_chat(chat_id)
        except TelegramAPIError as e:
            return await m.answer(f"Guruhga kira olmadim: {e}")
        await service.set_group(chat.id)
        await m.answer(f"Guruh saqlandi: {chat.title or chat.id} ({chat.id})")

    @r.message(Command("send"))
    async def send(m: Message, service: DutyService):
        res = await service.publish(service.today(), source="manual")
        texts = {
            "sent": f"Yuborildi (message_id={res.message_id}).",
            "already": f"Bugun allaqachon yuborilgan (message_id={res.message_id}).",
            "no_group": "Guruh belgilanmagan. /setgroup ishlating.",
            "failed": f"Xatolik: {res.error}",
        }
        await m.answer(texts.get(res.status, res.status))

    @r.message(Command("reset"))
    async def reset(m: Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Ha, tiklash", callback_data="reset:yes"),
            InlineKeyboardButton(text="Bekor qilish", callback_data="reset:no"),
        ]])
        await m.answer("Barcha 8 ta navbat boshiga qaytariladi. Tasdiqlaysizmi?", reply_markup=kb)

    @r.callback_query(F.data.in_({"reset:yes", "reset:no"}))
    async def reset_cb(cb: CallbackQuery, service: DutyService):
        if cb.data == "reset:yes":
            await service.reset_queues()
            text = "Barcha navbatlar boshiga qaytarildi."
        else:
            text = "Bekor qilindi."
        await cb.message.edit_text(text)
        await cb.answer()

    return r
