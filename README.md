# VIZCRM

Monorepo for the VIZCRM website, API, and mobile apps.

| Folder     | What                                                          |
|------------|---------------------------------------------------------------|
| `backend/` | Django website + REST API used by every app                   |
| `mobile/`  | pnpm workspace of Expo (React Native) apps for iOS & Android  |
| `docs/`    | Product spec and design notes                                 |

## Backend

Requires [uv](https://docs.astral.sh/uv/) (`brew install uv`).

```bash
cd backend
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py seed_demo_catalog --user <your-username>   # demo store + catalog
uv run python manage.py runserver
```

- Admin: http://127.0.0.1:8000/admin/
- API docs: http://127.0.0.1:8000/api/docs/
- JWT login for mobile: `POST /api/auth/token/`

## Mobile

Requires Node and pnpm (`brew install node pnpm`). iOS simulator needs Xcode;
Android emulator needs Android Studio. Or use the Expo Go app on a phone.

```bash
cd mobile
pnpm install
pnpm crm          # start the VIZCRM app dev server
```

Apps: `apps/crm` (VIZCRM). Planned: `pos`, `scanner`, `driver`.
Shared code goes in `packages/`.
