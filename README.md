# Dashboard SIN — Geração e Carga (ONS) — v2.0

Monitoramento automatizado do Sistema Interligado Nacional (SIN) a partir dos dados abertos do ONS, com ingestão incremental para **PostgreSQL** e **Dashboard Web interativo** hospedado no Railway.

- **Dashboard em produção (v2.0):** https://ingestor-production-805875a8.up.railway.app

```
S3 público do ONS ──► ingestor (Python) ──────────► PostgreSQL
(us-west-2 / .parquet)  ETag + upsert COPY (1h)      índice + views
                        + Servidor Web (:8000) ◄───── consultas em tempo real
```

## Evolução do Projeto (`v1.0` → `v2.0`)

### `v1.0` (Versão inicial rudimentar)
- Coleta manual de arquivos `.csv` avulsos do portal de dados abertos.
- Processamento local em script único, sem verificação de `ETag` e reprocessando arquivos inteiros a cada execução.
- Sem persistência estruturada em banco relacional nem histórico incremental idempotente.
- Sem cálculo automático de fator de capacidade ou detecção estatística de anomalias de despacho térmico.
- Visualizações estáticas locais, sem filtros por região/subsistema nem isolamento interativo por tipo de energia.

### `v2.0` (Versão atual)
- **Ingestão automatizada e idempotente:** consulta o bucket S3 público do ONS (`us-west-2`), prioriza arquivos `.parquet` (com fallback para `.csv`), verifica alterações via `ETag` (`ingest_log`) e realiza carga em lote via `COPY` + upsert (`ON CONFLICT ... IS DISTINCT FROM`).
- **Normalização e limpeza:** converte timestamps de Brasília (`America/Sao_Paulo`) para `UTC`, descarta linhas duplicadas e filtra a linha agregada `SIN` para evitar soma duplicada nos totais regionais.
- **Modelagem analítica no PostgreSQL:** `db.init_schema` cria automaticamente tabelas, índice temporal (`idx_balanco_subsistema_ts`) e views (`v_ultimo_instante`, `v_balanco_sin`, `v_capacidade_efetiva`, `v_fator_capacidade`, `v_alertas_termico`).
- **Dashboard Web integrado e interativo (`ons_ingest.web`):**
  - Barra de botões para ativar/ocultar cada gráfico individualmente.
  - Botões de **Região** (`N`, `NE`, `S`, `SE`, `Todas (SIN)`) e de **Tipo de Energia** (`Hidráulica`, `Térmica`, `Eólica`, `Solar`, `Carga`) para isolar uma região ou fonte com 1 clique (`Ctrl+Clique` para múltipla seleção).
  - **Legendas clicáveis** em todos os gráficos (clicar na cor ou nome isola aquela série; clicar novamente restaura todas).
  - Atualização automática a cada 60 segundos e zero dependência de ferramentas externas de BI.

## Arquitetura em Produção

No **Railway**, a aplicação roda com dois serviços conectados pela rede privada:

1. **Postgres** — banco PostgreSQL gerenciado com volume persistente.
2. **ingestor** (`python -m ons_ingest.main`) — inicializa o schema automaticamente (`db.init_schema`), executa o ciclo de ingestão em segundo plano a cada `POLL_INTERVAL_SECONDS` (padrão `3600`s) e serve o dashboard web na porta `PORT` (padrão `8000`, healthcheck em `/health`).

### Execução local (opcional)

```bash
cp .env.example .env        # configure DATABASE_URL
cd ingestor
pip install -r requirements.txt
python -m ons_ingest.main   # inicia ingestão + servidor web em http://localhost:8000
# ou apenas um ciclo sem servidor web:
python -m ons_ingest.main --once
```

## Painéis e Métricas

| Painel | Fonte |
|---|---|
| Carga, geração total, % renovável, térmica | `balanco_subsistema` no último instante completo |
| Dado mais recente + defasagem (min) | `v_ultimo_instante` |
| Matriz energética × carga (empilhado) | `balanco_subsistema`, com isolamento por região e fonte |
| Matriz no instante mais recente (rosca) | `balanco_subsistema` em `v_ultimo_instante` |
| Fator de capacidade eólica / solar | `v_fator_capacidade` |
| Térmica e intercâmbio por subsistema | `balanco_subsistema` |
| Alertas de despacho térmico | `v_alertas_termico` |

## Pontos de Atenção

- **Atraso natural da fonte:** o dataset do ONS é horário, mas publicado em lotes com defasagem. O card *Defasagem (min)* indica a idade do último dado completo (verde `< 180` min, laranja `≥ 180` min, vermelho `≥ 720` min).
- **Fator de capacidade:** sem capacidade instalada cadastrada na tabela `capacidade_instalada (subsistema, fonte, mw)`, a view `v_capacidade_efetiva` usa como proxy o máximo horário observado nos últimos 365 dias (`proxy_max_365d`).
- **Alertas térmicos:** heurística estatística configurável na tabela `alerta_config` (`CRITICO` = `z-score ≥ 3` ou rampa `≥ 1500 MW` em 3h; `ALTO` = `z-score ≥ 2` contra a média das 336h anteriores).
- **Fuso horário:** os dados do ONS chegam em `America/Sao_Paulo` e são armazenados em `UTC`; para anos anteriores a 2019 (com horário de verão), horas ambíguas na virada são descartadas.

## Testes

```bash
cd ingestor
pip install -r requirements.txt pytest
pytest -q
```

Cobrem parser (`parquet`/`;` CSV, conversão UTC, deduplicação, filtro de `SIN`, tratamento de schema), seleção de arquivos no S3 (preferência por `.parquet`), parsing de filtros da API e resposta HTTP dos endpoints `/health` e `/`.

## Próximos Passos / Upgrades Futuros

- **Docker e Containerização:** empacotar o serviço com `Dockerfile` e `docker-compose` para execução isolada e reprodutível em qualquer ambiente local ou nuvem.
- **Novos datasets do ONS:** ingerir o CMO semi-horário e a geração por usina para análise detalhada de despacho por ordem de mérito e CVU.
- **Notificações ativas de alerta:** disparo de avisos por e-mail ou webhook quando um subsistema entrar em nível `CRITICO`.
