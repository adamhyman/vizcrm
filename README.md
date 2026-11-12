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
uv run python manage.py seed_demo_catalog --user <your-username>   # demo company, store + catalog
uv run python manage.py runserver
```

- Admin: http://127.0.0.1:8000/admin/
- API docs: http://127.0.0.1:8000/api/docs/
- JWT login for mobile: `POST /api/auth/token/`
- Staff allowed at more than one store send the store's ID in an `X-Store` header
  (`GET /api/my-stores/` lists them); staff at a single store can leave it out.

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
