/*** ---- CONFIG ---- ***/
const SHEET_BOOKINGS = 'Заявки';
const CALENDAR_NAME   = 'Qwesade';            // имя календаря (создастся при первом запуске)
const DEFAULT_DURATION_MIN = 120;             // если указан только старт времени

/*** ---- UTILS ---- ***/
function getCalendar_() {
  const cals = CalendarApp.getCalendarsByName(CALENDAR_NAME);
  return cals[0] || CalendarApp.createCalendar(CALENDAR_NAME);
}

function getSheet_(name) {
  const ss = SpreadsheetApp.getActive();
  return ss.getSheetByName(name) || ss.insertSheet(name);
}

function headerMap_(sheet) {
  const headers = sheet.getRange(1,1,1,sheet.getLastColumn()).getValues()[0];
  const map = {};
  headers.forEach((h,i)=> map[String(h).trim()] = i+1);
  return map;
}

function ensureColumn_(sheet, colName) {
  const map = headerMap_(sheet);
  if (!map[colName]) {
    sheet.insertColumnAfter(sheet.getLastColumn());
    sheet.getRange(1, sheet.getLastColumn()).setValue(colName);
  }
  return headerMap_(sheet)[colName];
}

// slotText: "11:30–23:59", "11.30-23.59" или "11:30"
function parseSlot_(dateIso, slotText) {
  const SLOT = String(slotText || '')
    .replace(/[—–]/g,'-')
    .replace(/\./g,':')
    .replace(/\s+/g,''); // 19:00–21:00 -> 19:00-21:00

  const [y,m,d] = dateIso.split('-').map(Number);
  const fallbackStart = new Date(y, m-1, d, 12, 0);
  const fallbackEnd   = new Date(y, m-1, d, 14, 0);

  const m2h = (hhmm) => {
    const [hh,mm] = hhmm.split(':').map(v=>parseInt(v,10)||0);
    return {hh,mm};
  };

  // Диапазон
  if (/^\d{1,2}:\d{2}-\d{1,2}:\d{2}$/.test(SLOT)) {
    const [a,b] = SLOT.split('-');
    const A = m2h(a), B = m2h(b);
    const s = new Date(y, m-1, d, A.hh, A.mm);
    const e = new Date(y, m-1, d, B.hh, B.mm);
    return [s,e];
  }
  // Только старт
  if (/^\d{1,2}:\d{2}$/.test(SLOT)) {
    const A = m2h(SLOT);
    const s = new Date(y, m-1, d, A.hh, A.mm);
    const e = new Date(s.getTime() + DEFAULT_DURATION_MIN*60*1000);
    return [s,e];
  }
  return [fallbackStart,fallbackEnd];
}

/*** ---- MAIN SYNC (Bookings -> Google Calendar) ---- ***/
function syncBookingsToCalendar() {
  // Цвета по типу услуги (по желанию)
  const COLOR = {
    "Прогулка": CalendarApp.EventColor.GREEN,
    "Кафе": CalendarApp.EventColor.BLUE,
    "Кино": CalendarApp.EventColor.PALE_BLUE,
    "Спорт/зал/активность": CalendarApp.EventColor.SAGE,
    "Выезд на природу": CalendarApp.EventColor.MAUVE,
    "Разговор по душам": CalendarApp.EventColor.RED
  };

  const cal = getCalendar_();
  const ws  = getSheet_(SHEET_BOOKINGS);
  const colEventId = ensureColumn_(ws, 'CalendarEventId');

  const H = headerMap_(ws);
  const rng = ws.getRange(2,1, Math.max(ws.getLastRow()-1,0), ws.getLastColumn());
  const values = rng.getValues();

  for (let i=0; i<values.length; i++) {
    const row = values[i];
    const status    = String(row[H['Status']-1] || '').trim();
    const requestId = String(row[H['RequestID']-1] || '').trim();
    const dateIso   = String(row[H['DateISO']-1] || '').trim();
    if (!requestId || !dateIso) continue;

    const timeSlot  = String(row[H['TimeSlot']-1] || '').trim();
    const service   = String(row[H['Service']-1]  || '').trim();
    const user      = String(row[H['Username']-1] || row[H['TelegramID']-1] || '').trim();
    const district  = String(row[H['District']-1] || '').trim();
    const wishes    = String(row[H['Wishes']-1]   || '').trim();

    const eventCell  = ws.getRange(i+2, colEventId);
    const existingId = String(eventCell.getValue() || '').trim();

    if (status === 'Подтверждена') {
      const title = `${service}${user ? ' — @'+user : ''}`;
      const desc  = `RequestID: ${requestId}\nПожелания: ${wishes || '—'}`;
      const color = COLOR[service] || CalendarApp.EventColor.GRAY;

      // All-day?
      if (/весь\s*день/i.test(timeSlot)) {
        const [y,m,d] = dateIso.split('-').map(Number);
        const startDay = new Date(y, m-1, d);

        // Проще пересоздать all-day, чем конвертировать обычное событие
        if (existingId) {
          try {
            const oldEv = cal.getEventById(existingId);
            if (oldEv) oldEv.deleteEvent();
          } catch (e) {}
        }
        const ev = cal.createAllDayEvent(title, startDay, {location: district, description: desc});
        try { ev.setColor(color); } catch(e) {}
        eventCell.setValue(ev.getId());
        continue;
      }

      // Обычный интервал
      const [start, end] = parseSlot_(dateIso, timeSlot);
      let ev;
      if (existingId) {
        try {
          ev = cal.getEventById(existingId);
          if (ev) {
            ev.setTitle(title).setTime(start, end).setLocation(district).setDescription(desc);
          } else {
            ev = cal.createEvent(title, start, end, {location: district, description: desc});
          }
        } catch(e) {
          ev = cal.createEvent(title, start, end, {location: district, description: desc});
        }
      } else {
        ev = cal.createEvent(title, start, end, {location: district, description: desc});
      }
      try { ev.setColor(color); } catch(e) {}
      eventCell.setValue(ev.getId());

    } else if (status === 'Отклонена' || status === 'Отменена') {
      if (existingId) {
        try {
          const ev = cal.getEventById(existingId);
          if (ev) ev.deleteEvent();
        } catch(e) {}
        eventCell.setValue('');
      }
    }
  }
}

/*** ---- MONTH GRID RENDER (optional, for sheet "Календарь-Месяц") ---- ***/
function renderMonthGrid() {
  const ws = getSheet_('Календарь-Месяц');
  const year  = Number(ws.getRange('A1').getValue());
  const month = Number(ws.getRange('B1').getValue());
  if (!year || !month) return;

  const map = {};
  const bws = getSheet_(SHEET_BOOKINGS);
  const H = headerMap_(bws);
  const data = bws.getRange(2,1, Math.max(bws.getLastRow()-1,0), bws.getLastColumn()).getValues();

  data.forEach(r => {
    const status = String(r[H['Status']-1]||'').trim();
    if (status !== 'Подтверждена') return;
    const iso = String(r[H['DateISO']-1]||'').trim();
    if (!iso || iso.slice(0,7)!==Utilities.formatString('%04d-%02d', year, month)) return;
    const slot = String(r[H['TimeSlot']-1]||'').trim();
    const svc  = String(r[H['Service']-1] ||'').trim();
    const user = String(r[H['Username']-1]|| r[H['TelegramID']-1]||'').trim();
    const d = Number(iso.slice(8,10));
    const line = `${slot||''} ${svc}${user ? ' — @'+user : ''}`.trim();
    if (!map[d]) map[d] = [];
    map[d].push(line);
  });

  const rng = ws.getRange(4,1,6,7);
  const vals = rng.getValues();
  const out = vals.map(row => row.map(cell => {
    if (!cell) return '';
    const day = new Date(cell).getDate();
    const list = map[day] ? '\n' + map[day].join('\n') : '';
    return `${day}${list}`;
  }));
  rng.setValues(out);
  rng.setWrap(true);
}

/*** ---- ONE-TIME BEAUTY FOR SHEET "Календарь" ---- ***/
function formatCalendarSheet() {
  const ws = getSheet_('Календарь');
  ws.setFrozenRows(1);
  ws.setColumnWidths(1, 1, 110);      // Date
  ws.setColumnWidths(2, ws.getLastColumn()-1, 140);
  ws.getRange(1,1,1,ws.getLastColumn()).setFontWeight('bold').setHorizontalAlignment('center');
  ws.getRange(2,1,ws.getMaxRows()-1, ws.getLastColumn())
    .setWrap(true).setVerticalAlignment('top');
  // Мягкая подсветка занятых ячеек
  const rules = ws.getConditionalFormatRules();
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenTextDoesNotContain("")  // not empty
    .setBackground('#E6F4EA')
    .setRanges([ws.getRange(2,2,ws.getMaxRows()-1, ws.getLastColumn()-1)])
    .build());
  ws.setConditionalFormatRules(rules);
}

/*** ---- ONE-TIME INIT OF SHEETS ---- ***/

// какие слоты создать в «Календарь» по умолчанию (можно поменять)
const DEFAULT_SLOTS = ['Весь день','10:00–12:00','13:00–15:00','16:00–18:00','19:00–21:00'];

// шапка листа «Заявки» (ровно как в боте)
const BOOKINGS_HEADERS = [
  'Timestamp','RequestID','TelegramID','Username','Name',
  'Service','DateISO','DateText','TimeSlot','District','Wishes','Status','AdminComment'
];

function bootstrapSheets() {
  // создаём/берём листы
  const wsBook = getSheet_('Заявки');
  const wsCal  = getSheet_('Календарь');

  // --- «Заявки»: шапка, если пусто или криво
  let needBookHdr = true;
  if (wsBook.getLastRow() >= 1) {
    const first = (wsBook.getRange(1,1,1,BOOKINGS_HEADERS.length).getValues()[0] || []).join('|');
    if (first === BOOKINGS_HEADERS.join('|')) needBookHdr = false;
  }
  if (needBookHdr) {
    wsBook.clear();
    wsBook.getRange(1,1,1,BOOKINGS_HEADERS.length).setValues([BOOKINGS_HEADERS]);
    wsBook.setFrozenRows(1);
  }

  // --- «Календарь»: шапка из слотов
  const calHdr = ['Date'].concat(DEFAULT_SLOTS);
  wsCal.clear();
  wsCal.getRange(1,1,1,calHdr.length).setValues([calHdr]);
  wsCal.setFrozenRows(1);
  wsCal.getRange('A:A').setNumberFormat('yyyy-mm-dd');

  // красота (ширины, перенос, подсветка занятых ячеек)
  formatCalendarSheet();

  // подсказка
  SpreadsheetApp.getActive().toast('Листы и шапки готовы ✅', 'Qwesade', 5);
}

/*** ---- CUSTOM MENU IN SHEET ---- ***/
function onOpen() {
  SpreadsheetApp.getUi().createMenu('Qwesade')
    .addItem('Инициализировать листы', 'bootstrapSheets')
    .addItem('Синхронизация → Google Calendar', 'syncBookingsToCalendar')
    .addItem('Оформить лист «Календарь»', 'formatCalendarSheet')
    .addItem('Обновить «Календарь-Месяц»', 'renderMonthGrid')
    .addToUi();
}

