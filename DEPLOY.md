# Деплой Faceit Analytics в интернет

Две опции: **Render.com** (бесплатно, проще всего) и **VPS с Docker** (полный контроль).

---

## Вариант 1: Render.com (бесплатно, ~10 минут)

Render автоматически соберёт Docker-образ из `Dockerfile` и даст вам публичную ссылку вида `https://faceit-analytics.onrender.com`.

### Шаг 1. Загрузите код в GitHub

1. Зарегистрируйтесь на [github.com](https://github.com) (если нет аккаунта)
2. Создайте новый репозиторий (New repository), например `faceit-analytics`, **Public** или **Private** — не важно
3. Загрузите код. Самый простой способ без git-клиента: кнопка **«Add file → Upload files»** и перетащите туда **всё содержимое папки** `faceit-analytics` (папки `app/`, `static/`, файлы `Dockerfile`, `requirements.txt`, `.dockerignore`). Папку `__pycache__` не загружайте.

### Шаг 2. Создайте сервис на Render

1. Зайдите на [render.com](https://render.com) → войдите через GitHub («Sign up with GitHub»)
2. Нажмите **New → Web Service**
3. Выберите ваш репозиторий
4. Render сам увидит `Dockerfile` и предложит его использовать — оставьте как есть
5. Настройки:
   - **Instance Type:** Free (бесплатно; спит после 15 мин бездействия, первый запрос «разбудит» за ~30 сек — это нормально)
   - **Environment Variables** добавьте:

     | Имя | Значение |
     |---|---|
     | `SECRET_KEY` | длинная случайная строка (сгенерируйте: `python -c "import secrets; print(secrets.token_urlsafe(48))"`) |
     | `DATABASE_URL` | `sqlite:////tmp/faceit_analytics.db` ⚠️ см. примечание ниже |
     | `FACEIT_API_KEY` | ваш ключ Faceit Developer API (или пусто = demo-режим) |

6. Нажмите **Create Web Service**. Через 3–5 минут сервис будет готов, Render выдаст URL.

> ⚠️ **Примечание про БД на бесплатном тарифе Render.** Бесплатный диск непостоянный (ephemeral): при каждом деплое данные сбрасываются. Для теста/демо этого достаточно (SQLite в `/tmp`). Когда захотите хранить пользователей постоянно — подключите Render Postgres (тоже есть бесплатный план на 90 дней) и поставьте `DATABASE_URL` от него.

### Шаг 3. Готово

Откройте выданный URL — сервис доступен всем. Проверьте:
- главная страница открывается
- регистрация + логин работают
- профиль игрока загружается (demo-режим)

---

## Вариант 2: VPS с Docker (Hetzner / Selectel / любой)

Нужен сервер с Ubuntu 22.04+ и открытым портом 8000 (или nginx-прокси на 80/443).

```bash
# 1. Скопируйте проект на сервер
scp -r faceit-analytics user@ваш-сервер:~/

# 2. SSH на сервер
ssh user@ваш-сервер
cd ~/faceit-analytics

# 3. Установите Docker (если нет)
curl -fsSL https://get.docker.com | sh

# 4. Сгенерируйте SECRET_KEY и создайте .env
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))" > .env
echo "DATABASE_URL=sqlite:////app/data/faceit_analytics.db" >> .env
echo "FACEIT_API_KEY=" >> .env
cat .env

# 5. Соберите и запустите
docker compose up -d --build

# 6. Проверьте
docker compose logs -f          # дождитесь "Uvicorn running"
curl http://localhost:8000/api/health
```

Сервис будет на `http://ваш-ip:8000`. Для продакшена добавьте:
- **nginx** перед uvicorn (HTTPS через Let's Encrypt: `certbot`)
- **firewall**: `ufw allow 80,443 && ufw deny 8000` (порт 8000 только локально)
- автозапуск уже включён (`restart: unless-stopped`)

---

## Чек-лист перед выходом в массы

- [ ] `SECRET_KEY` заменён на случайный (иначе JWT можно подделать)
- [ ] `DEBUG=false`
- [ ] HTTPS (Render даёт автоматически; на VPS — certbot)
- [ ] Постоянное хранилище для БД (Render Postgres / volume на VPS)
- [ ] Реальный `FACEIT_API_KEY` (иначе все видят синтетические данные)
- [ ] Лимиты: rate limiter уже встроен (60 req/min/IP), капча на логине включена
