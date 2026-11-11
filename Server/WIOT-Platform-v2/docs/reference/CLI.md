# Command-line interface

_Generated from the code by `docs/tools/gen_reference.py` on 2026-11-11. Do not edit by hand._

```
usage: wiot [-h]
            {serve,init,create-user,reset-password,import-v1,check,analyze,simulate,devbroker} ...

WIOT Platform v2

positional arguments:
  {serve,init,create-user,reset-password,import-v1,check,analyze,simulate,devbroker}
    serve               run the API + dashboard server
    init                create databases and built-in accounts
    create-user         add a user
    reset-password      set a user's password (revokes sessions)
    import-v1           copy databases from a v1.31 server directory
    check               tenant storage preflight
    analyze             run the analytics + ML pipeline
    simulate            run an encrypted virtual fleet against a broker
    devbroker           start a local development MQTT broker

options:
  -h, --help            show this help message and exit
```

## `python -m wiot serve`

```
usage: wiot serve [-h] [--host HOST] [--port PORT]

options:
  -h, --help   show this help message and exit
  --host HOST
  --port PORT
```

## `python -m wiot init`

```
usage: wiot init [-h]

options:
  -h, --help  show this help message and exit
```

## `python -m wiot create-user`

```
usage: wiot create-user [-h] --role {supervisor,admin,monitor,user}
                        --company COMPANY [--password PASSWORD]
                        username

positional arguments:
  username

options:
  -h, --help            show this help message and exit
  --role {supervisor,admin,monitor,user}
  --company COMPANY
  --password PASSWORD
```

## `python -m wiot reset-password`

```
usage: wiot reset-password [-h] [--password PASSWORD] username

positional arguments:
  username

options:
  -h, --help           show this help message and exit
  --password PASSWORD
```

## `python -m wiot import-v1`

```
usage: wiot import-v1 [-h] [--force] source

positional arguments:
  source

options:
  -h, --help  show this help message and exit
  --force
```

## `python -m wiot check`

```
usage: wiot check [-h]

options:
  -h, --help  show this help message and exit
```

## `python -m wiot analyze`

```
usage: wiot analyze [-h] [--repo-root REPO_ROOT] [--out OUT]

options:
  -h, --help            show this help message and exit
  --repo-root REPO_ROOT
  --out OUT
```

## `python -m wiot simulate`

```
usage: wiot simulate [-h] [--host HOST] [--port PORT] [--aes-key AES_KEY]
                     [--companies COMPANIES] [--report-seconds REPORT_SECONDS]

options:
  -h, --help            show this help message and exit
  --host HOST
  --port PORT
  --aes-key AES_KEY
  --companies COMPANIES
  --report-seconds REPORT_SECONDS
```

## `python -m wiot devbroker`

```
usage: wiot devbroker [-h] [--host HOST] [--port PORT] [--bridge HOST[:PORT]]
                      [--bridge-topic FILTER]

options:
  -h, --help            show this help message and exit
  --host HOST
  --port PORT
  --bridge HOST[:PORT]  also bridge to an upstream broker where field gateways
                        publish (e.g. broker.hivemq.com)
  --bridge-topic FILTER
                        topic filter to bridge both ways; repeatable (default:
                        wiot/Company_1/#)
```
