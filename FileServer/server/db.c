#include "db.h"
#include <sqlite3.h>
#include <stdio.h>

/*
    THIS MODULE IMPLEMENTS DATABASE QUERIES TO SQLITE.
    IT'S NOT IN THE SCOPE OF THIS PROJECT TO CREATE A DATABASE STRUCTURE BUT ONLY TO 
    HANDLE IT. 

*/


static sqlite3 *db = NULL;      /* una connessione per processo, visibile solo qui */

int open_db(const char *path)
{
    if (db != NULL)              /* già aperta: non è un errore */
        return 0;

    if (sqlite3_open(path, &db) != SQLITE_OK) {
        fprintf(stderr, "open_db: %s\n", sqlite3_errmsg(db));
        sqlite3_close(db);       /* va chiusa anche se l'apertura fallisce */
        db = NULL;
        return -1;
    }

    sqlite3_busy_timeout(db, 5000);   /* se un altro processo scrive, aspetta fino a 5 s */

    /* Crea la tabella al primo avvio; le volte dopo non fa niente. */
    const char *schema =
        "PRAGMA journal_mode=WAL;"
        "CREATE TABLE IF NOT EXISTS files ("
        "  uuid    TEXT    PRIMARY KEY,"
        "  name    TEXT    NOT NULL,"
        "  size    INTEGER NOT NULL,"
        "  created INTEGER NOT NULL);";

    char *err = NULL;
    if (sqlite3_exec(db, schema, NULL, NULL, &err) != SQLITE_OK) {
        fprintf(stderr, "open_db: %s\n", err);
        sqlite3_free(err);
        close_db();
        return -1;
    }
    return 0;
}

void close_db(void)
{
    sqlite3_close(db);           /* con NULL non fa nulla, quindi è sicuro */
    db = NULL;
}

int insert_db(const file_record *f)
{
    sqlite3_stmt *st;
    const char *sql = "INSERT INTO files (uuid, name, size, created) VALUES (?, ?, ?, ?)";

    if (db == NULL) return -1;
    if (sqlite3_prepare_v2(db, sql, -1, &st, NULL) != SQLITE_OK) {
        fprintf(stderr, "insert_db: %s\n", sqlite3_errmsg(db));
        return -1;
    }

    sqlite3_bind_text(st, 1, f->uuid, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(st, 2, f->name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(st, 3, f->size);
    sqlite3_bind_int64(st, 4, f->created);

    int rc = sqlite3_step(st);
    int result = 0;
    if (rc == SQLITE_CONSTRAINT) {
        result = -2;                         /* uuid già presente */
    } else if (rc != SQLITE_DONE) {
        fprintf(stderr, "insert_db: %s\n", sqlite3_errmsg(db));
        result = -1;
    }
    sqlite3_finalize(st);
    return result;
}

int find_db(const char *name, file_record *out){
    sqlite3_stmt *st;
    const char *sql = "SELECT uuid, name, size, created FROM files WHERE name = ? "
                      "ORDER BY created DESC LIMIT 1";      /* se ce ne sono più, il più recente */

    if (db == NULL) return -1;
    if (sqlite3_prepare_v2(db, sql, -1, &st, NULL) != SQLITE_OK) {
        fprintf(stderr, "find_db_by_name: %s\n", sqlite3_errmsg(db));
        return -1;
    }

    sqlite3_bind_text(st, 1, name, -1, SQLITE_TRANSIENT);   /* cerco per nome */

    int rc = sqlite3_step(st);
    int result;
    if (rc == SQLITE_ROW) {                  /* trovato: dentro out c'è anche l'uuid */
        snprintf(out->uuid, sizeof out->uuid, "%s", (const char *)sqlite3_column_text(st, 0));
        snprintf(out->name, sizeof out->name, "%s", (const char *)sqlite3_column_text(st, 1));
        out->size    = sqlite3_column_int64(st, 2);
        out->created = sqlite3_column_int64(st, 3);
        result = 1;
    } else if (rc == SQLITE_DONE) {
        result = 0;                          /* nessun file con quel nome */
    } else {
        fprintf(stderr, "find_db_by_name: %s\n", sqlite3_errmsg(db));
        result = -1;
    }
    sqlite3_finalize(st);
    return result;
}


int delete_db(const char *uuid)
{
    sqlite3_stmt *st;
    const char *sql = "DELETE FROM files WHERE uuid = ?";

    if (db == NULL) return -1;
    if (sqlite3_prepare_v2(db, sql, -1, &st, NULL) != SQLITE_OK) {
        fprintf(stderr, "delete_db: %s\n", sqlite3_errmsg(db));
        return -1;
    }

    sqlite3_bind_text(st, 1, uuid, -1, SQLITE_TRANSIENT);

    int rc = sqlite3_step(st);
    int result;
    if (rc == SQLITE_DONE) {
        /* Un DELETE che non trova niente dà comunque SQLITE_DONE:
           sqlite3_changes dice se ha cancellato davvero una riga. */
        result = sqlite3_changes(db) > 0 ? 1 : 0;
    } else {
        fprintf(stderr, "delete_db: %s\n", sqlite3_errmsg(db));
        result = -1;
    }
    sqlite3_finalize(st);
    return result;
}