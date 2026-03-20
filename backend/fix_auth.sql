-- Creates an app user with mysql_native_password auth (PyMySQL compatible).
-- MariaDB 12 defaults to GSSAPI auth which PyMySQL doesn't support.

USE tfg_demencia;

CREATE USER IF NOT EXISTS 'tfg_app'@'localhost'
  IDENTIFIED VIA mysql_native_password
  USING PASSWORD('tfg_pass_2024');

GRANT ALL PRIVILEGES ON tfg_demencia.* TO 'tfg_app'@'localhost';
FLUSH PRIVILEGES;

SELECT 'OK: user tfg_app created' AS result;
