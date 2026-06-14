# finance-monorepo

## Postman Maintenance

- After any API router or request/response model change, run `make postman` (and `make postman-push` if `POSTMAN_API_KEY` is set) and commit the regenerated `openapi/` and `postman/` files, including the prod template at `postman/render.postman_environment.json`.
