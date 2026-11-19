# CSV Import Studio v6 — Multi-Database Space Edition

โปรแกรมนำเข้า CSV/TXT ที่เลือกไฟล์จากคอมพิวเตอร์ นับจำนวนแถว แสดง Preview (ขยายได้) แก้ชื่อคอลัมน์ปลายทาง / เลือก Data Type และเลือกฐานข้อมูลเป้าหมายจากหน้าจอเดียว **ไม่แก้ไขค่าในไฟล์ CSV ต้นฉบับ**

## สิ่งที่รองรับ

| ปลายทาง | ที่อยู่ข้อมูล | Create | Append | Upsert | Replace | การเชื่อมต่อ |
|---|---|---|---|---|---|---|
| MySQL / MariaDB | Schema (=Database) / Table | ✔ | ✔ | ✔ | ✔ | Host, Port, Username, Password |
| PostgreSQL | Database → Schema → Table | ✔ | ✔ | ✔ | ✔ | Host, Port, Username, Password, ชื่อ Database ที่มีอยู่ |
| SQLite | ไฟล์ .db → Schema `main` → Table | ✔ | ✔ | ✔ | ✔ | เลือกไฟล์ .db หรือสร้างใหม่ |
| MongoDB | Database / Collection | ✔ | ✔ | ✔ | ✔ | Host, Port, Username, Password (ปล่อย User ว่างได้เมื่อไม่ใช้ Auth) |

**หมายเหตุ:** ใช้คำว่า "Schema" ใน PostgreSQL แต่ MongoDB ใช้ Database และ Collection ที่ไม่มีโครงสร้างคอลัมน์ตายตัว ส่วน SQLite ใช้ `main` เสมอ จึงไม่ต้องสร้าง Schema แยก โปรแกรมไม่ได้สร้าง *PostgreSQL Database* ใหม่ (ต้องมี Database ก่อน) แต่สร้าง *PostgreSQL Schema* ใหม่ได้

## เปิดโปรแกรมบน Windows

1. ติดตั้ง Python 3.10+ พร้อมส่วนประกอบ Tkinter (python.org) และแตก ZIP
2. ดับเบิลคลิก `install_windows.bat` ครั้งแรก เพื่อติดตั้ง PyMySQL, psycopg และ PyMongo (ต้องใช้อินเทอร์เน็ต) ส่วน SQLite อยู่ใน Python แล้ว
3. ดับเบิลคลิก `open_demo.pyw` เพื่อทดลองหน้าจอโดยไม่ต่อฐานข้อมูล หรือ `open_app.pyw` เพื่อใช้งานจริง
4. หาก `.pyw` ไม่ขึ้น ให้เปิด `run_demo_windows.bat` / `run_windows.bat` เพื่อดู Error หรืออ่านไฟล์ `startup_error.log`
5. เลือก CSV → ดู Preview และจำนวนแถว → เลือก Schema/Table และโหมด → เลือกชนิดฐานข้อมูลที่ขั้นตอน 03 → เชื่อมต่อ → ตั้งค่าคอลัมน์ → กดเริ่มนำเข้า

## วิธีเชื่อมต่อแต่ละประเภท

**MySQL:** เริ่มต้น 127.0.0.1:3306 ต้องมี Username/Password ที่ได้รับสิทธิ์ → Schema เดิมหรือเลือกสร้างใหม่ → Table → โหมด Import

**PostgreSQL:** เลือก PostgreSQL แล้วกรอก Host, Port 5432, Username, Password และ **Database สำหรับเชื่อมต่อ** (ค่าเริ่มต้น postgres) → เลือก Schema เช่น public หรือสร้าง Schema ใหม่ → เลือก Table

**SQLite:** เลือก SQLite → คลิก "เลือกไฟล์" เพื่อเลือก/ระบุ `.db` (หากพิมพ์ชื่อใหม่ในโฟลเดอร์ที่มีอยู่ SQLite จะสร้างไฟล์เมื่อกด Test Connection) → ใช้ Schema main → ตั้งชื่อ Table

**MongoDB:** เลือก MongoDB → กรอก Host และ Port 27017, Username/Password เมื่อจำเป็น (โปรแกรมตั้ง authSource=admin สำหรับการล็อกอินด้วย Username) → กรอกชื่อ Database และ Collection; ในโหมด Create สามารถระบุชื่อ Database ใหม่ได้ โดย MongoDB สร้างฐานข้อมูลเมื่อมี Collection และข้อมูลจริง ไม่ต้องติ๊ก Create Schema

**MongoDB Atlas/Cluster แบบ SRV** และกรณี AuthSource ไม่ใช่ `admin` ยังไม่รองรับหน้าตั้งค่าพิเศษในเวอร์ชันนี้; ใช้การเชื่อมต่อ host/port ปกติได้

เมื่อไม่มีสิทธิ์ `listDatabases` ระบบยังให้กรอกชื่อ Database ที่ได้รับสิทธิ์เองได้ แต่ต้องมีสิทธิ์เข้าถึง Collection ที่จะนำเข้าจริง

## สิ่งสำคัญเกี่ยวกับ Data Type

- สร้าง MySQL/PostgreSQL/SQLite: เลือก Data Type ใน Column Mapping ผ่าน Dropdown คลิกเลือกโดยตรง (ค่าเริ่มต้น `TEXT`)
- SQLite มีชนิดข้อมูลภายในไม่เหมือน SQL Server ทั่วไป: `TEXT`, `VARCHAR`, `DATE`, `DATETIME` จะเก็บเป็น TEXT, `INT/BIGINT` เป็น INTEGER, `DECIMAL/DOUBLE` เป็น REAL ตาม SQLite affinity
- MongoDB ไม่มีชนิดคอลัมน์ตายตัว: ค่าเริ่มต้นเก็บ CSV เป็น **ข้อความ**; ถ้าเลือก `INT/BIGINT`, `DOUBLE`, `DECIMAL`, `DATE`, `DATETIME` โปรแกรมจะแปลงเป็น BSON ตามที่ผู้ใช้เลือกโดยเจตนา; สามารถเลือก Data Type ได้แม้เป็นการนำเข้าลง Collection เดิม
- แก้ชื่อคอลัมน์ใน Mapping เป็นการเปลี่ยน **ชื่อที่บันทึกลงปลายทาง** ไม่แก้ Header ใน CSV; สำหรับ SQL Table ที่มีอยู่แล้วต้องจับคู่คอลัมน์เดิม; MongoDB สามารถเพิ่มฟิลด์ใหม่ได้
- PostgreSQL และ SQLite ไม่ได้เก็บข้อมูล `VARCHAR`/`DECIMAL` เหมือน MySQL ทุกกรณี ควรตรวจชนิดข้อมูลก่อนใช้

## ความปลอดภัยและข้อจำกัด

- โปรแกรมไม่บันทึก Password ลงไฟล์ และไม่เปลี่ยนข้อมูลไฟล์ CSV ต้นฉบับ
- ค่าข้อมูลทั้งหมดถูกส่งแบบ Parameterized SQL สำหรับ MySQL/PostgreSQL/SQLite หรือ BSON documents สำหรับ MongoDB; ชื่อปลายทางผ่านการตรวจสอบก่อนใช้ในคำสั่งฐานข้อมูล
- **Replace** ต้องพิมพ์ `REPLACE` เพื่อยืนยัน และควรสำรองปลายทางก่อนเสมอ
- MySQL ใช้ engine นำเข้าเดิมของ v5 โดยไม่เปลี่ยนไฟล์ `importer_core.py`; MySQL Replace ยังจำกัด InnoDB เพื่อ Rollback
- SQLite/PostgreSQL Create/Replace ใช้ Transaction สำหรับการ Rollback เมื่อผิดพลาด; SQLite ทดลองกับฐานข้อมูลจริงแล้ว
- MongoDB Create/Replace ใช้ Collection staging ก่อนเปลี่ยนชื่อปลายทาง; Replace พยายามคง Indexes แต่จะปฏิเสธ Collection ที่มี Options พิเศษ เช่น Validator เพื่อไม่ทำลายการตั้งค่าเดิม; การสลับชื่อขึ้นกับเวอร์ชัน Server การตั้งค่า Cluster และสิทธิ์ renameCollection
- **Append/Upsert** ของ MySQL และ MongoDB อาจบันทึกบางชุดแล้วก่อนพบข้อผิดพลาด; บางกรณีไม่สามารถย้อนคืนได้ทั้งหมด
- MongoDB Upsert จำเป็นต้องมี Single-field Unique Index/`_id` บนคีย์ที่เลือก และ CSV ต้องมีคีย์นั้น; SQL Upsert ต้องมี Unique Key ที่รองรับ
- UTF-8/ไทย/0 นำหน้า/เครื่องหมาย `'` ในค่า TEXT ถูกเก็บตามต้นฉบับ ข้อมูลชนิดตัวเลข/วันที่ขึ้นอยู่กับการแปลงของฐานข้อมูลที่เลือก
- การเชื่อมต่อ Server จริงต้องมี IP/Firewall, สิทธิ์ DB และ Driver ถูกต้อง โปรแกรมไม่ส่งข้อมูลผ่านบริการอื่นใดนอกเหนือจาก Database ที่คุณระบุ

## โครงสร้างไฟล์

- `app.py` — Tkinter ธีมอวกาศ, Preview, Column Mapping, เลือกประเภทฐานข้อมูลและเปิด Import
- `importer_core.py` — Core อ่าน CSV + Engine MySQL เดิมจาก v5
- `database_backends.py` — Connector และ Import Engine PostgreSQL / SQLite / MongoDB พร้อมตัวเรียก MySQL เดิม
- `open_app.pyw`, `open_demo.pyw` — เริ่มโปรแกรมโดยไม่เปิด CMD; `run_windows.bat` / `run_demo_windows.bat` — ใช้ดูปัญหาใน CMD
- `install_windows.bat`, `requirements.txt` — ติดตั้ง Driver ฐานข้อมูล
- `assets/` — รูปธีมอวกาศ
- `tests/` — Unit/GUI tests รวมถึง SQLite integration
- `DESIGN.md`, `UX-CONTRACT.md` — ข้อมูลอ้างอิงเรื่องหน้าตาและพฤติกรรมระบบ

## ทดสอบด้วยตัวเอง

เปิด CMD จากโฟลเดอร์โปรแกรม จากนั้นรัน `py -m unittest discover -s tests -p "test_*.py"` สำหรับชุด unittest เดิม; ชุด pytest ใหม่ใช้ `py -m pip install pytest` และ `py -m pytest -q tests/`

> ชุดทดสอบในสภาพแวดล้อมผู้สร้างผ่านการทดสอบ SQLite และการทำงาน UI แบบจำลอง แต่ **ยังไม่ได้เชื่อม PostgreSQL/MongoDB/MySQL Server จริงในเครื่องของผู้ใช้** ขอให้ทดสอบฐานข้อมูลสำรองก่อนนำไปใช้งานจริง
