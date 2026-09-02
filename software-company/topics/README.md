# Topics

Mỗi file JSON Schema mô tả envelope + payload của một topic. Bus (`src/company/bus.py`)
validate trước khi ghi. Owner ghi của `shared-context` theo namespace:

| namespace | owner |
|---|---|
| prd | spec-writer |
| glossary | domain |
| architecture, api-contract (khởi tạo) | delivery-lead |
| api-contract (cập nhật) | backend |
| schema | database |
| docs | support-docs |
| knowledge | supervisor |
