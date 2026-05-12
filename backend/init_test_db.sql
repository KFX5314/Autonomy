-- MariaDB database used only by automated tests.
-- Run as a user with CREATE DATABASE / GRANT privileges.

CREATE DATABASE IF NOT EXISTS tfg_demencia_test
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'tfg_app'@'localhost'
  IDENTIFIED VIA mysql_native_password
  USING PASSWORD('tfg_pass_2024');
CREATE USER IF NOT EXISTS 'tfg_app'@'127.0.0.1'
  IDENTIFIED VIA mysql_native_password
  USING PASSWORD('tfg_pass_2024');

GRANT ALL PRIVILEGES ON tfg_demencia_test.* TO 'tfg_app'@'localhost';
GRANT ALL PRIVILEGES ON tfg_demencia_test.* TO 'tfg_app'@'127.0.0.1';
FLUSH PRIVILEGES;

SELECT 'OK: tfg_demencia_test ready' AS result;
