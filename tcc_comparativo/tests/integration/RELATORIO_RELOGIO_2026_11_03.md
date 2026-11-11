# Interrupção da série por ajuste de relógio

Na primeira tentativa da planta completa, seed 20261101, o gerador e os dois bancos registraram 893.924 mensagens. O stream reportou zero descartes e zero erros de escrita, mas seis das latências confirmadas foram negativas, entre −2.531 e −2.538 ms. A sequência de confirmações teve um recuo de 2.534 ms no ponto correspondente.

O evento 145050 do log de sistema do Windows registrou um ajuste de −2.542,661 ms às 10h20min05s, horário local. O recuo observado nos timestamps dos containers aparece aproximadamente seis segundos depois no relógio apresentado pelos registros. A proximidade dos valores e dos horários é evidência de uma relação, mas não determina o mecanismo exato de propagação do ajuste entre host e containers.

Pelo menos 11.117 latências batch atravessam, de forma inequívoca pelos timestamps registrados, o intervalo do recuo observado; outros registros próximos ao intervalo têm ordenação ambígua. A réplica foi rejeitada e seus arquivos originais foram preservados. Corrigir os valores a posteriori exigiria hipóteses não comprovadas sobre o instante e a propagação do ajuste.

Nos arquivos das três réplicas reduzidas e das três intermediárias não foram detectados recuos na sequência de confirmações stream nem ajustes de pelo menos 1 ms no log do Windows nas janelas auditadas. As verificações foram registradas em `metrics/clock_audit.json` de cada execução. Isso não prova a ausência de toda possível anomalia de relógio.

As três réplicas da planta completa serão refeitas com as mesmas seeds e imagens da tentativa rejeitada. A auditoria adicionada roda depois da coleta e rejeita saltos detectados nas confirmações ou ajustes relevantes registrados pelo Windows, sem alterar a instrumentação durante as medições.

Os logs das seis réplicas anteriores registram uso de cache nas etapas de build, sem downloads de dependências, mas os identificadores das imagens registrados por execução são diferentes. Como as imagens antigas não estão mais disponíveis localmente para inspeção, não foi comprovada diretamente a equivalência dos seus conteúdos. A retomada reutiliza as imagens da tentativa completa rejeitada sem reconstruí-las; seus identificadores ficam registrados em cada pasta de métricas.

Na retomada, a primeira réplica completa, seed 20261101, passou na reconciliação e na auditoria. A segunda, seed 20261102, gerou e persistiu 893.858 registros em cada abordagem, mas apresentou duas latências stream negativas, de −1 ms e −2 ms. Não houve recuo detectado na sequência de confirmações nem evento de ajuste relevante no Windows. A consulta aos pontos no InfluxDB identificou `ingested_at` 4 ms posterior ao instante de confirmação dessas mensagens, uma ordem inconsistente; o mecanismo exato permanece não determinado.

O usuário optou por manter a instrumentação e refazer somente as réplicas completas com seeds 20261102 e 20261103. A auditoria pós-execução foi ajustada para identificar também latências negativas, mesmo quando a sequência das confirmações não mostra recuo. Ela registra o resultado em `clock_audit_v2.json`, preservando os arquivos da auditoria anterior. A verificação detecta anomalias observáveis, mas não impede ajustes do relógio nem comprova ausência de todas as inconsistências possíveis.
