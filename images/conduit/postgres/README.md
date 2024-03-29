# Postgres Conduit

## Publishing manually

Requires:

- [`docker`](https://www.docker.com)
- [`aws` CLI](https://aws.amazon.com/cli/)

From this image directory:

1. `aws sso login`
2. `aws ecr-public get-login-password --region us-east-1 | docker login --username AWS --password-stdin public.ecr.aws/uktrade`
3. `docker build -t public.ecr.aws/uktrade/tunnel:postgres .`
4. `docker tag public.ecr.aws/uktrade/tunnel:postgres public.ecr.aws/uktrade/tunnel:postgres-$(git rev-parse --short HEAD)`
5. `docker push public.ecr.aws/uktrade/tunnel:postgres`
6. `docker push public.ecr.aws/uktrade/tunnel:postgres-$(git rev-parse --short HEAD)`
7. `docker logout public.ecr.aws/uktrade`

## Testing locally

Requires:

- [`docker`](https://www.docker.com)
- [`docker-compose`](https://docs.docker.com/compose/)

Steps:

1. `docker-compose up` to bring up the client and database
2. `docker-compose exec client bash` to connect to the database
3. You will now be in a `psql` session, run `\list` to check available schemas
4. Enter `ctrl+d` or `\q` to exit.
5. Note that the client container will now show a shutdown countdown in `docker-compose` logs every 60 seconds.
