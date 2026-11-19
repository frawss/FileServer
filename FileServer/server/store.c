#include"store.h"
#include<stdio.h>
#include<stdint.h>
#include<string.h>
#include<unistd.h>
#include<errno.h>
#include<fcntl.h>
#include <uuid/uuid.h>

#define OPENING_TEMP_ERROR -1
#define OPENING_BIN_ERROR -2
#define MAX_SIZE 8192
#define WRITING_ERROR -20
#define DELETING_ERROR -19

// this part of the code is the one responsible of:
// 1) finding
// 2) saving 
// 3) getting
// and such with all the values 




// i'm gonna insert the value inside the filesystem 
// we are gonna take the file by streaming it 
// with a socket, by reading 8KB everycicl, then store it.


// we must assume that the socket is ok
// sd: socket descriptor
// uint64_t is the length



int insert_disco(int sd, uint64_t length,char *nome_finale,char *uuid ){
    // Dentro insert_disco...
    uint64_t counter = 0;
    uint64_t da_leggere = 0;
    char percorso_file[8192];
    char percorso_finale[8192];
    int fd=-1;
    ssize_t result=0;
    char buff[MAX_SIZE];
    snprintf(percorso_file, sizeof(percorso_file), "./storage/%s.temp", uuid);
    snprintf(percorso_finale, sizeof(percorso_finale), "./storage/%s.bin", uuid);
    
    if((fd=open(percorso_file,O_WRONLY | O_CREAT | O_TRUNC ,0644))<0){
        printf(" il file %s non è stato aperto \n",percorso_file);
        return OPENING_BIN_ERROR;
    }

    while (counter < length) {
    // Calcola quanti byte mancano. Se mancano più di 8KB, leggi 8KB. 
    // Se ne mancano di meno (es. ultimo blocco da 500 byte), leggi solo 500 byte.
        da_leggere = length - counter;
        if (da_leggere > MAX_SIZE) {
            da_leggere = MAX_SIZE;
        }

        result = read(sd, buff, da_leggere);
        if (result < 0 && errno == EINTR) continue;
    
        if (result <= 0) {
        // Errore o disconnessione improvvisa del client
            close(fd);
            remove(percorso_file);
            return WRITING_ERROR;
        }

        // Qui controlliamo != result per assicurarci di aver scritto TUTTO il frammento
        ssize_t scritti = 0;
        while (scritti < result) {
            ssize_t w = write(fd, buff + scritti, result - scritti);
            if (w < 0 && errno == EINTR) continue;
            if (w <= 0) {
                close(fd);
                remove(percorso_file);
                return WRITING_ERROR;
            }
            scritti += w;
        }

        counter += result;
    }

    // Se usciamo dal while, significa che counter == length. Perfetto.
    if (fsync(fd) != 0) {
        close(fd);
        remove(percorso_file);
        return WRITING_ERROR;
    }
    close(fd);
    if (rename(percorso_file, percorso_finale) != 0) {
        remove(percorso_file);
        return WRITING_ERROR;
    }
    return 0;
}

int delete_file(char *uuid){
    
    char percorso_finale[256];
    snprintf(percorso_finale, sizeof(percorso_finale), "./storage/%s.bin", uuid);
    // Attempt to delete the file
    if (remove(percorso_finale) == 0) {
        printf("File deleted successfully.\n");
        return 0;
    } else {
        printf("Error: Unable to delete the file.\n");
        return DELETING_ERROR;
    }

   
    return 0;
}


//read the file from the disk and sending it with sd
int find_file(int sd,char *uuid){
    int result=0;
    char percorso_finale[256];
    int fd=-1;
    char buff[MAX_SIZE];

    snprintf(percorso_finale, sizeof(percorso_finale), "./storage/%s.bin", uuid);
    
    if((fd=open(percorso_finale,O_RDONLY))<0){
        printf(" il file %s non è stato aperto \n",percorso_finale);
        return OPENING_BIN_ERROR;
    }
    
    
    while((result = read(fd, buff,MAX_SIZE))>0){
        int inviati = 0;
        while (inviati < result) {
            int w = write(sd, buff + inviati, result - inviati);
            if (w < 0 && errno == EINTR) continue;
            if (w <= 0) {
                close(fd);
                return WRITING_ERROR;
            }
            inviati += w;
        }
    }
    if (result < 0) {
        close(fd);
        return WRITING_ERROR;
    }
    

    close(fd);
    
    return 0;
}