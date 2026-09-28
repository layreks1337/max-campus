"""Генерация PDF-документов по заявкам.

fpdf2 выбран сознательно: чистый Python, никаких системных зависимостей —
в Docker и на Windows результат одинаковый. Шрифт PT Sans (OFL) лежит в репозитории,
потому что кириллица во встроенных шрифтах fpdf отсутствует.

Юридическая оговорка: документ НЕ имеет электронной подписи. Подлинность
проверяется по QR-коду на странице /verify/<uuid>. Это честно проговаривается
и в самом документе, и на защите.
"""

from __future__ import annotations

import io
import logging
import uuid as uuid_lib
from datetime import datetime, timedelta
from pathlib import Path

import qrcode
from fpdf import FPDF
from fpdf.enums import XPos, YPos

from app.core.config import settings
from app.db.models import Document, Request, Student, utcnow

log = logging.getLogger("requests.pdf")

FONT_DIR = Path(__file__).resolve().parents[3] / "assets" / "fonts"
# Форма учреждения — общая для государственных вузов. Название вуза — из настроек
# (UNIVERSITY_NAME): новый вуз подключается без правки кода.
UNIVERSITY = "Федеральное государственное бюджетное образовательное учреждение"

MONTHS_GEN = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def ru_date(dt: datetime) -> str:
    return f"{dt.day} {MONTHS_GEN[dt.month - 1]} {dt.year} г."


class CampusPDF(FPDF):
    def __init__(self) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=20)
        self._register_fonts()

    def _register_fonts(self) -> None:
        regular = FONT_DIR / "PTSans-Regular.ttf"
        bold = FONT_DIR / "PTSans-Bold.ttf"
        if not regular.exists():
            raise FileNotFoundError(
                f"Не найден шрифт {regular}. Шрифты лежат в репозитории "
                "(backend/assets/fonts) — проверьте, что папка попала в образ"
            )
        self.add_font("PT", "", str(regular))
        self.add_font("PT", "B", str(bold) if bold.exists() else str(regular))

    # fpdf2 после multi_cell по умолчанию оставляет курсор у ПРАВОГО края блока.
    # Следующий вызов с шириной 0 получает нулевую доступную ширину и падает с
    # «Not enough horizontal space». Поэтому каждый блок явно возвращает курсор
    # к левому полю.
    def _text_block(self, height: float, text: str, align: str = "L") -> None:
        self.set_x(self.l_margin)
        self.multi_cell(
            0, height, text, align=align, new_x=XPos.LMARGIN, new_y=YPos.NEXT
        )

    def header_block(self) -> None:
        self.set_font("PT", "", 9)
        self.set_text_color(90, 90, 90)
        self._text_block(4.5, UNIVERSITY, "C")
        self.set_font("PT", "B", 11)
        self.set_text_color(20, 20, 20)
        self._text_block(6, f"высшего образования\n«{settings.UNIVERSITY_NAME}»", "C")
        self.ln(2)
        self.set_draw_color(200, 200, 200)
        self.line(20, self.get_y(), 190, self.get_y())
        self.ln(8)

    def title_block(self, title: str, number: str, date: datetime) -> None:
        self.set_font("PT", "B", 18)
        self.set_text_color(20, 20, 20)
        self._text_block(9, title.upper(), "C")
        self.ln(2)
        self.set_font("PT", "", 10)
        self.set_text_color(110, 110, 110)
        self._text_block(5, f"№ {number} от {ru_date(date)}", "C")
        self.ln(6)

    def body_text(self, text: str) -> None:
        self.set_font("PT", "", 12)
        self.set_text_color(20, 20, 20)
        for para in text.split("\n"):
            if para.strip():
                self._text_block(7, para.strip())
            else:
                self.ln(3)
        self.ln(4)

    def signature_block(
        self, issued_by: str, position: str = "Специалист деканата", caption: str = "подпись"
    ) -> None:
        self.ln(10)
        y = self.get_y()
        self.set_font("PT", "", 11)
        self.set_text_color(20, 20, 20)
        self.set_xy(20, y)
        self.cell(75, 7, position, new_x=XPos.LEFT, new_y=YPos.TOP)
        self.set_xy(115, y)
        self.cell(75, 7, issued_by, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(180, 180, 180)
        self.line(115, y + 7, 190, y + 7)
        self.set_xy(115, y + 7)
        self.set_font("PT", "", 8)
        self.set_text_color(140, 140, 140)
        self.cell(75, 5, caption, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def verification_block(self, verify_url: str) -> None:
        qr = qrcode.QRCode(box_size=10, border=1)
        qr.add_data(verify_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        # Блок прижимаем к низу страницы, но не даём наехать на текст выше
        y = min(max(self.get_y() + 12, 232), 250)
        self.image(buf, x=20, y=y, w=28, h=28)

        text_x, text_w = 54, 136

        self.set_xy(text_x, y + 1)
        self.set_font("PT", "B", 9)
        self.set_text_color(20, 20, 20)
        self.cell(text_w, 5, "Проверка подлинности", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        self.set_xy(text_x, y + 7)
        self.set_font("PT", "", 8)
        self.set_text_color(110, 110, 110)
        self.multi_cell(
            text_w,
            4,
            f"Отсканируйте QR-код или откройте {verify_url}\n"
            "Страница покажет, кому и когда выдан документ и действует ли он.",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

        self.set_xy(text_x, y + 19)
        self.set_font("PT", "", 7)
        self.set_text_color(160, 160, 160)
        self.multi_cell(
            text_w,
            3.5,
            "Демонстрационный документ, сформированный в MAX Campus. "
            "Усиленная квалифицированная электронная подпись не применялась.",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )


# ── Тексты документов ─────────────────────────────────────────────


def _study_certificate(req: Request, s: Student) -> str:
    purpose = req.payload_json.get("purpose", "по месту требования")
    return (
        f"Дана {s.full_name}, {s.birth_date or '—'} года рождения, в том, что "
        f"он(а) действительно является студентом(кой) {s.course} курса "
        f"{s.faculty}, группа {s.group_name}, "
        f"{s.education_form} формы обучения, на местах, финансируемых "
        f"из средств {'федерального бюджета' if s.funding == 'бюджет' else 'по договору об оказании платных услуг'}.\n"
        f"\nНомер зачётной книги: {s.record_book_no}.\n"
        f"Год зачисления: {s.enrolled_year}.\n"
        f"\nСправка выдана для предъявления: {purpose}."
    )


def _military_certificate(req: Request, s: Student) -> str:
    return (
        f"Дана {s.full_name} в том, что он действительно обучается на {s.course} курсе "
        f"{s.faculty}, группа {s.group_name}, по очной форме обучения.\n"
        f"\nСрок обучения: {s.enrolled_year} — {s.enrolled_year + 4} гг.\n"
        f"Номер зачётной книги: {s.record_book_no}.\n"
        "\nСправка выдана для предъявления в военный комиссариат."
    )


def _income_certificate(req: Request, s: Student) -> str:
    period = req.payload_json.get("period", "текущий семестр")
    return (
        f"Дана {s.full_name}, студенту(ке) {s.course} курса {s.faculty}, "
        f"группа {s.group_name}, в том, что за период «{period}» "
        "начислялась государственная академическая стипендия.\n"
        "\nСведения о размере начислений предоставляются бухгалтерией "
        "по отдельному запросу.\n"
        "\nСправка выдана для предъявления по месту требования."
    )


def _decision(req: Request, s: Student) -> str:
    title = req.template.title.lower()
    return (
        f"Рассмотрено заявление {s.full_name}, студента(ки) {s.course} курса "
        f"{s.faculty}, группа {s.group_name}.\n"
        f"\nПредмет обращения: {title}.\n"
        "\nРешение: заявление принято к рассмотрению, документы приняты в полном объёме.\n"
        "\nО результате заявитель уведомлён через сервис MAX Campus."
    )


BODY_BUILDERS = {
    "study_certificate": _study_certificate,
    "military_certificate": _military_certificate,
    "income_certificate": _income_certificate,
}


def build_body(req: Request) -> str:
    builder = BODY_BUILDERS.get(req.template.doc_template, _decision)
    return builder(req, req.student)


# ── Публичная функция ─────────────────────────────────────────────


def generate_document(
    req: Request, issued_by: str, *, automatic: bool = False
) -> tuple[str, Path, datetime]:
    """Формирует PDF. Возвращает (uuid, путь к файлу, срок действия).

    automatic — справку выдал не сотрудник, а автовыдача типовых документов:
    в блоке подписи так и написано, без имитации росчерка.
    """
    doc_uuid = str(uuid_lib.uuid4())
    now = utcnow()
    valid_until = now + timedelta(days=90)
    verify_url = f"{settings.MINIAPP_PUBLIC_URL.rstrip('/')}/verify/{doc_uuid}"

    pdf = CampusPDF()
    pdf.add_page()
    pdf.header_block()
    pdf.title_block(req.template.short_title or req.template.title, req.public_no, now)
    pdf.body_text(build_body(req))
    pdf.body_text(f"Действительна до {ru_date(valid_until)}")  # ru_date уже с точкой: «г.»
    if automatic:
        pdf.signature_block(issued_by, "Выдано автоматически", "без подписи сотрудника")
    else:
        pdf.signature_block(issued_by)
    pdf.verification_block(verify_url)

    safe_title = (req.template.doc_template or "document").replace(" ", "_")
    file_name = f"{safe_title}_{req.public_no}.pdf"
    file_path = settings.documents_dir / f"{doc_uuid}.pdf"
    pdf.output(str(file_path))

    log.info("Сформирован документ %s для заявки %s", file_name, req.public_no)
    return doc_uuid, file_path, valid_until


def make_document_record(
    req: Request, issued_by: str, *, automatic: bool = False
) -> Document:
    doc_uuid, path, valid_until = generate_document(req, issued_by, automatic=automatic)
    safe_title = (req.template.doc_template or "document").replace(" ", "_")
    return Document(
        request_id=req.id,
        uuid=doc_uuid,
        file_name=f"{safe_title}_{req.public_no}.pdf",
        file_path=str(path),
        issued_by=issued_by,
        valid_until=valid_until,
    )
