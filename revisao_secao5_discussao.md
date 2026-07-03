# 5. DISCUSSÃO DOS RESULTADOS

A discussão a seguir consolida os resultados dos três experimentos conduzidos, correspondentes às cargas de 1x, 2x e 4x, cada qual executada por 60 minutos sob as mesmas condições de ambiente. Diferentemente de uma análise organizada por nível de carga, optou-se aqui por uma estrutura orientada às métricas, na qual cada subseção examina uma dimensão de desempenho e compara, no mesmo conjunto de gráficos, o comportamento das abordagens batch e stream ao longo das três cargas. Essa organização favorece a observação direta das tendências de escalabilidade, que tenderiam a se dispersar em uma análise carga a carga. São avaliadas quatro dimensões principais, a saber, o volume de dados processados, a latência fim a fim, o throughput e a utilização de recursos computacionais, seguidas de uma análise de escalabilidade e da comparação com a literatura.

## 5.1. VOLUME DE DADOS PROCESSADOS

A primeira dimensão analisada corresponde ao volume total de dados efetivamente persistido por cada abordagem, apresentado na Figura X. Na ingestão em stream, os pontos gravados no InfluxDB acompanharam o crescimento da carga, partindo de 285.422 registros em 1x, passando por 474.039 em 2x e alcançando 2.054.542 em 4x. A contagem do próprio consumidor stream, referente às mensagens recebidas via MQTT e enfileiradas para escrita, foi de 285.559, 523.058 e 1.041.148, respectivamente, sem nenhuma mensagem descartada e sem erros de escrita em qualquer dos cenários. Esse comportamento indica que o pipeline contínuo absorveu integralmente o fluxo gerado, mesmo sob a carga mais elevada.

Na ingestão em batch, o PostgreSQL registrou 285.695, 570.897 e 3.409.347 registros para as cargas de 1x, 2x e 4x. Cabe observar, entretanto, uma inconsistência no cenário de 4x, em que os arquivos CSV efetivamente processados somaram 1.136.367 linhas, ao passo que a tabela relacional acumulou 3.409.347 registros, aproximadamente o triplo desse valor. Esse descompasso evidencia o acúmulo de dados residuais de execuções anteriores na mesma tabela, e não um volume real de ingestão superior. Por essa razão, as comparações de volume e de escalabilidade que dependem da contagem absoluta da tabela batch no cenário de 4x devem ser interpretadas com cautela, sendo a contagem de linhas dos arquivos CSV e os totais do lado stream as referências mais confiáveis do volume realmente processado em cada execução. Esse aspecto é retomado na Seção 5.5.

De modo geral, a métrica de volume confirma que ambos os pipelines respondem ao aumento da carga, mas o stream fornece uma medida mais limpa e auditável do que foi efetivamente ingerido, em razão da instrumentação de contadores fim a fim presente no consumidor.

## 5.2. LATÊNCIA FIM A FIM

A latência fim a fim, definida como o intervalo entre a criação da leitura na fonte (created_at) e sua efetiva persistência no banco (ingested_at), é a métrica em que as duas abordagens mais se distanciam, e esse contraste se mantém consistente nas três cargas avaliadas.

### 5.2.1. Batch (PostgreSQL)

A Figura X consolida a distribuição da latência de carga no PostgreSQL para as três cargas, considerando o valor mínimo, a mediana (P50), o percentil 95 (P95) e o valor máximo. O padrão é dominado pelo intervalo do agendador, fixado em 5 minutos. A latência média manteve-se em torno de 184,2 s na carga de 1x, 182,0 s em 2x e 166,1 s em 4x, com mediana praticamente idêntica à média, em 184,0 s, 182,0 s e 165,8 s. O percentil 95 alcançou 321,0 s, 319,2 s e 298,7 s, enquanto os valores máximos aproximaram-se do teto teórico de espera de um ciclo completo, registrando 359,9 s, 358,9 s e 326,8 s.

Dois aspectos merecem destaque. Em primeiro lugar, a latência batch é estruturalmente elevada, da ordem de três minutos em média e de até seis minutos no pior caso, uma vez que cada registro aguarda o disparo subsequente do agendador. Em segundo lugar, e de forma contraintuitiva, a latência média não cresce com o aumento da carga, permanecendo estável e até decrescendo levemente em 4x. Isso ocorre porque o componente dominante da latência é o tempo de enfileiramento, ou seja, a espera pelo ciclo, e não o tempo de processamento. Como o processamento de cada lote consome poucos segundos, o aumento de volume não amplia a janela de espera, apenas torna cada lote mais populoso. A latência batch é, portanto, governada pela política de agendamento, e não pela intensidade da carga aplicada.

### 5.2.2. Stream (InfluxDB)

A abordagem stream opera em outra ordem de grandeza. Conforme o monitoramento em tempo de execução realizado por meio do Grafana, o delay manteve-se abaixo de 200 milissegundos na carga de 1x, oscilou predominantemente entre 100 e 800 milissegundos em 2x e, em 4x, conservou a maioria das amostras abaixo de 500 milissegundos, ainda que com picos esporádicos que ultrapassaram 2.400 milissegundos. Dessa forma, mesmo na carga mais elevada, a latência típica do stream permaneceu na ordem das centenas de milissegundos, cerca de três ordens de grandeza inferior à observada no batch.

O comportamento dos picos no cenário de 4x é coerente com o modelo descrito por Das et al. (2014), segundo o qual a latência cresce de forma não linear à medida que a taxa de dados se aproxima da capacidade de processamento disponível, com degradações mais pronunciadas nos percentis mais altos. Ainda assim, o pipeline não acumulou fila pendente nem descartou mensagens, o que indica que tais picos foram transitórios e absorvidos sem perda de dados. A diferença de latência entre as abordagens é, portanto, qualitativa e não apenas quantitativa, dado que o batch entrega os dados em minutos por construção, enquanto o stream entrega em tempo quase real e se degrada apenas de forma marginal sob estresse.

## 5.3. THROUGHPUT

O throughput revela a diferença mais sutil entre as abordagens, pois cada modelo expressa sua vazão de maneira distinta, contínua no stream e concentrada em rajadas no batch. A Figura X apresenta as duas leituras de forma justaposta.

No stream, o throughput médio sustentado, calculado como a razão entre os pontos escritos no InfluxDB e a janela ativa do gerador de sensores, cresceu de forma praticamente proporcional à carga, partindo de aproximadamente 79 mensagens por segundo em 1x, alcançando 145 em 2x e 317 em 4x. Esse fluxo apresenta-se constante e ininterrupto, característica desejável em aplicações que exigem resposta contínua.

No batch, a leitura relevante corresponde à distribuição do throughput por lote processado, representada por um diagrama de caixa. Cada lote é carregado em rajada, com vazões instantâneas bastante elevadas, cuja mediana foi de aproximadamente 22.600 registros por segundo em 1x, 29.700 em 2x e 28.000 em 4x, com picos superiores a 30.000 registros por segundo. Esses valores, à primeira vista superiores aos do stream, refletem a própria natureza do modelo, que não processa continuamente, mas concentra grande volume em poucos segundos a cada ciclo, permanecendo ocioso no intervalo restante. A vazão instantânea elevada, portanto, não se traduz em entrega rápida, constituindo a contrapartida direta da latência elevada discutida na Seção 5.2.

A leitura conjunta das duas métricas sintetiza o trade-off central deste trabalho, em que o batch se mostra orientado a volume, com alta vazão por ciclo e baixa frequência de execução, enquanto o stream se mostra orientado a velocidade, com vazão moderada, porém contínua e de baixa latência, distinção alinhada ao que é defendido por Benjelloun et al. (2020).

## 5.4. UTILIZAÇÃO DE RECURSOS (CPU E MEMÓRIA)

A análise dos dados obtidos a partir dos logs do Docker permite avaliar o custo computacional de cada abordagem nas três cargas, com base no uso médio de CPU (%) e de memória (MiB) por container. A Figura X consolida esses valores, e a Figura X apresenta a série temporal de CPU do consumidor stream ao longo dos experimentos.

O consumidor stream apresentou crescimento de CPU proporcional e previsível em relação à carga, com uso médio de 3,78% em 1x, 5,97% em 2x e 9,80% em 4x. Seu consumo de memória, por outro lado, manteve-se notavelmente estável, em torno de 34,5 a 35,7 MiB nas três cargas, com variação inferior a 2 MiB entre os cenários de 1x e 4x. Essa estabilidade de memória, também visível na série temporal, é uma das características mais favoráveis do modelo stream, uma vez que o consumo permanece constante por serem os dados processados à medida que chegam, sem acúmulo em buffer.

O consumidor batch apresentou menor uso médio de CPU, com 1,58% em 1x, 2,15% em 2x e 3,00% em 4x, comportamento coerente com seu padrão de atividade concentrada, no qual o processo permanece majoritariamente ocioso e desperta a cada ciclo do agendador, gerando picos pontuais de CPU, com máximos entre 33% e 39%, intercalados por longos períodos de baixa atividade. Em contrapartida, o custo de armazenamento da abordagem batch recai sobre o banco relacional, cuja memória média cresceu de 68,9 MiB em 1x para 160,5 MiB em 2x e 347,4 MiB em 4x, refletindo o esforço de indexação e manutenção da tabela à medida que o volume acumulado aumenta.

Os serviços de apoio mantiveram baixo impacto em todas as cargas. O broker MQTT Mosquitto operou com uso de CPU entre 2,0% e 4,8% e memória entre 25 e 45 MiB mesmo em 4x, sem saturação, o que reforça a adequação do MQTT como protocolo leve para cenários IoT. O gerador de sensores escalou conforme o esperado, com uso médio de CPU de 5,0%, 6,8% e 12,0%, confirmando que a fonte de carga acompanhou os multiplicadores configurados.

Em síntese, as duas abordagens distribuem o custo de recursos de formas distintas. O stream concentra o trabalho no consumidor, com CPU crescente, porém memória estável, enquanto o batch alivia o consumidor, mas transfere a pressão de memória e de pico de CPU para o banco relacional. Em nenhum dos cenários os recursos do ambiente foram saturados, o que indica a existência de margem para volumes ainda mais elevados.

## 5.5. ESCALABILIDADE

Com o objetivo de avaliar a escalabilidade de forma direta, a Figura X apresenta as razões de cada métrica entre cargas sucessivas (2x/1x e 4x/2x) e a razão total (4x/1x). Um escalonamento perfeitamente linear corresponderia a 2,0 por passo e a 4,0 no acumulado.

O lado stream exibe o comportamento mais próximo do ideal. O throughput escalou em 1,83 entre 1x e 2x, 2,18 entre 2x e 4x e 3,99 no total, padrão praticamente linear de ponta a ponta, o que indica que a vazão de ingestão cresce na mesma proporção da carga oferecida. O uso de CPU do consumidor stream cresceu de forma sublinear, com razões de 1,58, 1,64 e 2,59 no total, de modo que quadruplicar a carga custou aproximadamente 2,6 vezes mais CPU, evidência de eficiência crescente por unidade de dado processada e sinal positivo de escalabilidade.

O lado batch deve ser interpretado à luz da ressalva apontada na Seção 5.1. A contagem de registros do PostgreSQL escalou em 2,00 entre 1x e 2x, mas saltou para 5,97 entre 2x e 4x e 11,93 no total, valores muito acima do esperado. Esse comportamento anômalo decorre do acúmulo de dados residuais na tabela do cenário de 4x, e não de uma escalabilidade real superlinear, visto que o número de linhas dos arquivos CSV efetivamente processados, de aproximadamente 1,14 milhão, é consistente com o previsto para o cenário. Recomenda-se, para trabalhos futuros, assegurar a reinicialização das tabelas entre execuções, de modo que a métrica de volume da abordagem batch se torne diretamente comparável.

Conclui-se, portanto, que o pipeline stream escala de forma linear e previsível em vazão, com custo de CPU sublinear e memória constante, ao passo que o batch mantém a latência estável por construção, embora sua escalabilidade de volume não tenha sido medida de forma limpa neste conjunto de execuções, em razão do resíduo presente na tabela relacional.

## 5.6. COMPARAÇÃO COM A LITERATURA

Os resultados obtidos nos experimentos estão alinhados com os achados descritos na literatura, especialmente no que se refere ao comportamento distinto entre os modelos de processamento em lote e em fluxo contínuo.

Benjelloun et al. (2020) destacam que abordagens streaming são mais eficazes em ambientes que exigem baixa latência e resposta imediata. Tal observação é coerente com os dados obtidos neste trabalho, nos quais o stream manteve delay tipicamente inferior a 1 segundo, mesmo sob cargas elevadas, enquanto o batch apresentou latências sistematicamente superiores a 160 segundos, o que compromete sua aplicação em cenários sensíveis ao tempo. Os mesmos autores distinguem os processamentos como sendo o batch orientado a volume e o stream orientado a velocidade, distinção evidenciada de forma quantitativa na Seção 5.3, em que o batch obteve alta vazão apenas em janelas isoladas, ao custo de longos intervalos de espera entre ciclos.

A instrumentação por containers permitiu observar que o modelo streaming concentra a pressão sobre o consumidor de ingestão, com CPU crescente e memória estável, enquanto o batch transfere o custo de armazenamento ao banco relacional, cuja memória mais que quintuplicou da carga de 1x para a de 4x. Esse padrão complementa a observação de Tatipamula (2025), segundo a qual sistemas de streaming demandam provisionamento dimensionado para picos de carga.

Por fim, Das et al. (2014) demonstram empiricamente que a latência cresce de forma não linear à medida que o volume se aproxima da capacidade disponível, com degradações especialmente pronunciadas nos percentis mais altos. Esse comportamento foi observado sob carga de 4x, na qual o stream manteve operação contínua e sem perdas, mas com picos de latência significativamente acima da média, ultrapassando 2.400 milissegundos, enquanto a maioria das amostras permaneceu abaixo de 500 milissegundos.

De forma geral, os dados obtidos confirmam as limitações e vantagens discutidas nos estudos analisados. A abordagem streaming oferece maior estabilidade, previsibilidade de escalonamento e tempo de resposta, enquanto o batch é mais eficiente em processamentos agregados e análises históricas. Essa distinção é fundamental para orientar a escolha do modelo conforme o perfil da aplicação.

## 5.7. LIMITAÇÕES

Este estudo foi conduzido em um ambiente simulado, com o objetivo de reproduzir, de forma prática e controlada, o comportamento de uma planta industrial. Embora o modelo de sensores tenha sido desenhado para refletir cenários realistas, tanto em frequência quanto em variabilidade dos dados, a ausência de ruídos externos e instabilidades presentes em ambientes reais constitui uma limitação importante no que diz respeito à generalização dos resultados.

As comparações entre as estratégias de ingestão foram realizadas com uma única configuração de hardware e rede, o que significa que os resultados obtidos podem não se manter sob infraestruturas diferentes, como máquinas com múltiplos núcleos ou arquiteturas distribuídas. Da mesma forma, somente duas tecnologias específicas foram avaliadas, sendo o InfluxDB para ingestão em stream e o PostgreSQL para ingestão em batch, o que implica que as conclusões não podem ser automaticamente extrapoladas para outras ferramentas que adotem os mesmos paradigmas de ingestão.

Ainda que todas as métricas de uso de CPU, memória, throughput e latência tenham sido monitoradas continuamente, não foram realizados testes de perda de pacotes, consistência de dados ou tempo de resposta ao consumidor final, uma vez que tais aspectos não faziam parte do escopo do tipo de teste aplicado. Além disso, conforme discutido nas Seções 5.1 e 5.5, a tabela relacional do cenário de 4x acumulou registros residuais de execuções anteriores, o que compromete a comparabilidade direta da métrica de volume da abordagem batch nesse cenário, recomendando-se que trabalhos futuros assegurem a reinicialização das tabelas entre execuções.

O experimento foi executado por 60 minutos em cada cenário, com testes sob três níveis de carga de trabalho, normal (1x), dobrado (2x) e quadruplicado (4x). O rate limit dos sensores foi fixado nesses níveis, o que restringe a avaliação a uma faixa específica de estresse do sistema.

---

## Apêndice da revisão — valores consolidados (referência rápida)

A tabela a seguir reúne os valores citados ao longo da Seção 5, servindo como referência rápida para verificação. Não se destina a integrar o corpo final do texto, mas a apoiar a conferência dos números e a montagem das figuras.

| Métrica | 1x | 2x | 4x |
|---|---|---|---|
| Pontos persistidos — InfluxDB (stream) | 285.422 | 474.039 | 2.054.542 |
| Mensagens recebidas — consumidor stream | 285.559 | 523.058 | 1.041.148 |
| Mensagens descartadas | 0 | 0 | 0 |
| Registros — PostgreSQL (batch)¹ | 285.695 | 570.897 | 3.409.347¹ |
| Linhas nos CSVs processados (batch) | 285.695 | 570.897 | 1.136.367 |
| Latência batch — média (s) | 184,2 | 182,0 | 166,1 |
| Latência batch — P95 (s) | 321,0 | 319,2 | 298,7 |
| Latência stream — típica (Grafana) | < 200 ms | 100–800 ms | < 500 ms (picos > 2.400 ms) |
| Throughput stream médio (msg/s) | ≈ 79 | ≈ 145 | ≈ 317 |
| Throughput batch — mediana por lote (reg/s) | ≈ 22.600 | ≈ 29.700 | ≈ 28.000 |
| CPU média — consumidor stream (%) | 3,78 | 5,97 | 9,80 |
| Memória média — consumidor stream (MiB) | 34,5 | 34,8 | 35,7 |
| CPU média — consumidor batch (%) | 1,58 | 2,15 | 3,00 |
| Memória média — PostgreSQL (MiB) | 68,9 | 160,5 | 347,4 |
| Escalonamento throughput stream (4x/1x) | — | — | 3,99 (≈ linear) |
| Escalonamento CPU stream (4x/1x) | — | — | 2,59 (sublinear) |

¹ O valor da tabela PostgreSQL em 4x inclui registros residuais de execuções anteriores. A contagem de linhas dos CSVs (1.136.367) é a referência confiável do volume realmente processado nesse cenário.

### Figuras comparativas geradas (`tcc_comparativo/Figs/comparativo/`)

- `fig_volume.png` — Volume total por carga (batch no PostgreSQL e stream no InfluxDB).
- `fig_latencia_batch.png` — Distribuição da latência batch (mínimo, P50, P95 e máximo) por carga.
- `fig_throughput.png` — Throughput stream médio e distribuição do throughput batch por lote.
- `fig_recursos.png` — CPU e memória médias dos consumidores e do banco batch por carga.
- `fig_cpu_timeseries.png` — Série temporal de CPU do consumidor stream nas três cargas.
- `fig_escalabilidade.png` — Razões de escalonamento entre cargas (2x/1x, 4x/2x e 4x/1x).
