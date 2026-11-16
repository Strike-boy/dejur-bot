from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from services.duty_service import DutyService

router = Router()

HELP = (
    "Buyruqlar:\n"
    "/today - bugungi navbatchilar\n"
    "/next - ertangi navbatchilar\n"
    "/help - yordam\n\n"
    "Bot har kuni 20:00 da (Toshkent vaqti) guruhga e'lon yuboradi."
)


@router.message(Command("start"))
async def start(m: Message):
    await m.answer("Assalomu alaykum! WIUT yotoqxona oshxona navbatchilik boti.\n\n" + HELP)


@router.message(Command("help"))
async def help_(m: Message):
    await m.answer(HELP)


@router.message(Command("today"))
async def today(m: Message, service: DutyService):
    await m.answer(await service.today_text())


@router.message(Command("next"))
async def next_(m: Message, service: DutyService):
    await m.answer(await service.next_text())
