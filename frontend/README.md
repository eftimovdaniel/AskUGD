# AskUGD Frontend

Локална копија од [ugd.edu.mk](https://www.ugd.edu.mk) + AskUGD чат виджет.

## Како да се отвори (без сервер)

1. Отвори го фајлот во browser:
   - `frontend/index.html` (двоен клик или drag во Chrome/Safari)
2. Виџетот е долу десно (црвено копче).

**Не треба** `npm start`. Frontend е статичен.

Backend стартувај само кога сакаш одговори од AI (`http://127.0.0.1:8000`).

## Структура

```
frontend/
├── index.html          ← почетна (клон од УГД)
├── za-ugd/, upisi/, …  ← локални подстраници
├── Styles/, Scripts/   ← CSS/JS од сајтот
├── assets/             ← икони за виџетот
├── src/                ← TypeScript извор на виџетот
├── dist/custom.js      ← build на виџетот
└── styles.css          ← UGD стилови + AskUGD виджет
```

## Ако менуваш код на виџетот

```bash
cd frontend
npm install
npm run build
```

Потоа повторно отвори `index.html`.
