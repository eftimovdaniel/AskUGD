# AskUGD Frontend

Чат виджет (TypeScript) за AskUGD асистентот.

## Структура

```
frontend/
├── src/           # TypeScript извор
├── assets/        # икони / лого
├── dist/          # build → custom.js
├── styles.css     # стилови на виџетот
└── index.html     # демо страница
```

## Стартување

```bash
cd frontend
npm install
npm run build
npm start
```

Отвори http://localhost:3000 — виџетот е долу десно.

## Embed на друга страница

```html
<script
  id="ugd-ai-agent-script"
  src="/dist/custom.js"
  data-api-url="http://127.0.0.1:8000"
></script>
```
