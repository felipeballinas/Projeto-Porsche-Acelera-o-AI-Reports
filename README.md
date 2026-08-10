# Schema da Base de Dados Porsche

## Visão Geral

Este documento descreve a estrutura da base de dados utilizada no projeto "Porsche AI Reports".

A base contém informações de vendas de veículos Porsche, incluindo dados comerciais, financeiros e operacionais.

---

# Estrutura da Tabela

| Campo | Tipo | Descrição |
|---------|---------|---------|
| sale_id | Integer | Identificador único da venda |
| sale_date | String | Data original da venda |
| SaleDateSanitized | Date | Data validada e padronizada |
| customer_name | String | Nome do cliente |
| porsche_model | String | Modelo original do veículo |
| PorscheModelSanitized | String | Modelo padronizado |
| model_year | String | Ano original do modelo |
| ModelYearSanitized | Integer | Ano validado do veículo |
| sale_price | String | Valor original da venda |
| SalesPriceSanitized | Decimal | Valor monetário padronizado |
| vehicle_mileage | String | Quilometragem original |
| VehicleMileageSanitized | Integer | Quilometragem convertida para número |
| payment_method | String | Forma de pagamento original |
| PayMethodSanitized | String | Forma de pagamento padronizada |
| city | String | Cidade original |
| CitySanitized | String | Cidade padronizada |
| state | String | Estado original |
| StateSanitized | String | Estado padronizado |
| salesperson | String | Vendedor responsável |
| delivery_status | String | Status original da entrega |
| DeliveryStatusSanitized | String | Status padronizado da entrega |

---

# Campos Utilizados pelo Agente de IA

O agente utiliza prioritariamente os seguintes campos sanitizados:

- SaleDateSanitized
- PorscheModelSanitized
- ModelYearSanitized
- SalesPriceSanitized
- VehicleMileageSanitized
- PayMethodSanitized
- CitySanitized
- StateSanitized
- DeliveryStatusSanitized

Esses campos garantem maior consistência analítica e reduzem problemas causados por erros de preenchimento.

---

# Regras de Negócio

## Datas

- Datas inválidas são identificadas como INVALID.
- Somente datas válidas devem ser utilizadas em análises temporais.

## Valores Monetários

- Todos os valores são convertidos para formato decimal.
- Moeda utilizada: USD.

## Quilometragem

- Quilometragem armazenada como valor numérico inteiro.
- Valores textuais são convertidos durante a sanitização.

## Status de Entrega

Valores permitidos:

- Delivered
- Pending
- In Transit
- Awaiting Delivery
- Awaiting Pickup
- Pending Approval
- Pending Review
- Awaiting Review
- Shipped
- Cancelled

## Métodos de Pagamento

Valores padronizados:

- Credit Card
- Debit Card
- Bank Transfer
- Wire Transfer
- Financing
- Lease
- Cash
- ACH Payment
- Crypto Payment

---

# Objetivo Analítico

A estrutura da base foi projetada para permitir:

- Análise de vendas;
- Avaliação de faturamento;
- Cálculo de ticket médio;
- Análise geográfica;
- Monitoramento logístico;
- Identificação de padrões de compra;
- Geração de AI Reports;
- Produção de insights por Inteligência Artificial.

---

# Saída Esperada do Agente

O agente deve ser capaz de:

1. Interpretar os dados disponíveis.
2. Identificar inconsistências.
3. Gerar relatórios executivos.
4. Produzir insights de negócio.
5. Responder perguntas em linguagem natural.
6. Apresentar recomendações baseadas nos dados.
