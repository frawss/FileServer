#ifndef DB_H
#define DB_H

int insert_disco(int sd, uint64_t length,char *nome_finale,char *uuid );
int delete_file(char *uuid);
int find_file(int sd,char *uuid);

#endif