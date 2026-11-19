#ifndef DB_H
#define DB_H

#include <stdint.h>

typedef struct {
    char    uuid[37];
    char    name[256];
    int64_t size;
    int64_t created;
} file_record;

int  open_db(const char *path);                       /* 0 ok, -1 errore */
void close_db(void);
int  insert_db(const file_record *f);                 /* 0 ok, -1 errore, -2 uuid già presente */
int find_db(const char *name, file_record *out);     /* 1 trovato, 0 non trovato, -1 errore */
int  delete_db(const char *uuid);                     /* 1 cancellato, 0 non c'era, -1 errore */

#endif