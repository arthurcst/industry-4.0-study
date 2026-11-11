# Painéis Grafana do TCC

O Grafana é disponibilizado em http://localhost:5005. O dashboard provisionado fica na pasta TCC, com o nome **TCC — Stream vs Batch**.

Os seletores de bucket e tabela representam os cenários reduzido, intermediário e completo. Os painéis exibem somente os arquivos de confirmação da execução ativa: ao selecionar outro cenário, não há dados. Para consultar outra execução, é necessário montar os arquivos dela na fonte auxiliar e reiniciá-la com o cenário correspondente.

| Painel | Significado |
|---|---|
| Confirmações por segundo, batch ou stream | Quantidade de mensagens com confirmação registrada em cada segundo, incluindo segundos sem confirmação entre a primeira e a última observação no intervalo selecionado. |
| Latência até a confirmação, batch ou stream | Média por segundo do intervalo entre a criação e a confirmação recebida pelo cliente, em milissegundos. |
| Stream, média nos últimos 2 min | Confirmações dos últimos 120 segundos divididas por 120, incluindo segundos sem confirmação. No início da execução, parte da janela pode anteceder a geração. |
| Batch, média por minuto | Confirmações em cada minuto divididas por 60. Minutos parcialmente incluídos no filtro também são divididos por 60. |

Uma confirmação é atribuída ao instante em que o cliente recebe a resposta de escrita, compartilhado por todos os registros daquela operação. Ausência de confirmações não identifica, por si só, a causa: podem ocorrer pausas normais de lote, falhas ou atraso na coleta.

O serviço auxiliar `metrics-db` usa `file_fdw` para ler os CSVs `latency_batch.csv` e `latency_stream.csv` da execução ativa. Os CSVs são persistidos no diretório da execução e montados em modo somente de leitura no banco auxiliar. O banco auxiliar é temporário e não contém cópia durável dos dados. `metrics-prepare` cria os arquivos vazios quando ainda não existem, sem apagar o conteúdo existente.

O Grafana consulta os arquivos a cada 30 segundos. Essas leituras e o banco auxiliar consomem recursos compartilhados com o experimento, portanto o monitoramento pode afetar as medições. Os CSVs e os resumos por execução devem ser preservados como fonte de análise do trabalho.

Não utilize os painéis antigos baseados em `ingested_at - created_at` como latência até a confirmação. Contagens de confirmação também não são equivalentes a identificação de mensagens perdidas: a análise de perdas exige conferir os identificadores produzidos, recebidos e confirmados.
