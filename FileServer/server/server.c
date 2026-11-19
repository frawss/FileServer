#include<arpa/inet.h>
#include<endian.h>
#include<errno.h>
#include<inttypes.h>
#include<netdb.h>
#include<stdint.h>
#include<time.h>
#include<netinet/in.h>
#include<signal.h>
#include<stdio.h>
#include<stdlib.h>
#include<string.h>
#include<sys/socket.h>
#include<sys/types.h>
#include<sys/wait.h>
#include<unistd.h>
#include<uuid/uuid.h>
#include"db.h"
#include"store.h"
#define SOCKET_ERR -10
#define SUCCESS_CODE 0
#define WRITING_ERR -11
#define INSERT_ERR -12
#define FIND_ERR -13
#define DELETE_ERR -14
#define INSERT_DB_ERR -20
#define FIND_DB_ERR -21
#define OPENDB_ERR -22
#define DB_NOT_FOUND -23
#define MAX_UPLOAD  (100ULL * 1024 * 1024)     /* 100 MB */



// WHAT IT DOES?
/*

    this code handles network's implementation by 
    taking metadatas from the handler such as file's length and then
    passing all it needs to the level below such as store.c.
    I created a: parser and sockets handling in order to pass it to store.c.
    I used TCP. 

*/

// i have to assume for future implementation that i need also the operation 
// which i put a limit to 8 char UPLOAD DELETE SEARCH or similar
typedef struct {
    uint64_t length;
    char operation[16];
    char namefile[64];
}header;

/*  WE HAVE TO SEND BACK A MESSAGE ERROR TO THE CLIENTS, SO WE LET THEM KNOW WHAT HAPPENED
    WE USE CODE TO KNOW WHICH MESSAGE WE HAVE TO SEND, TWO DIFFERENT FUNCTION:

    1) FOR SUCCESS CODE
    2) FOR ERROR CODE AND RETRY 


*/

static int send_all(int fd, const void *buf, size_t len);

int send_back_msg(int conn_sd,int code){
    
    char error[128] = {0};
    if(code==SUCCESS_CODE) snprintf(error, sizeof(error), "%s", "OPERAZIONE RIUSCITA");
    else snprintf(error, sizeof(error), "%s%d","ERRORE: NON SONO RIUSCITO NELL'OPERAZIONE, CODICE: ", code);
    
    return send_all(conn_sd,error,sizeof(error));
}

/* I NEED THIS FUNCTION TO READ ALL THE DATA FOR THE HEADER */

static int read_all(int fd, void *buf, size_t len)
{
    char *p = buf;
    while (len > 0) {
        ssize_t n = read(fd, p, len);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;                  /* errore, timeout o client disconnesso */
        p += n;
        len -= (size_t)n;
    }
    return 0;
}


static int send_all(int fd, const void *buf, size_t len)
{
    const char *p = buf;
    while (len > 0) {
        ssize_t n = send(fd, p, len, 0);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        p += n;
        len -= (size_t)n;
    }
    return 0;
}


/* Il nome arriva dal client: niente '/', niente nomi che iniziano con '.' */
static int valid_name(const char *s)
{
    if (s[0] == '\0' || s[0] == '.') return 0;
    return strchr(s, '/') == NULL;
}


/*
    I use a functor to have a more scalable and clean code,
    If i want to add any more operation, i need to add a function instead of having a long list of if-else.
*/

void generate_new_uuid(char *str_uuid_dest) {
    uuid_t binuuid;
    
    // 1. Genera l'UUID binario (16 byte grezzi)
    uuid_generate(binuuid);
    
    // 2. Converte i 16 byte in una stringa esadecimale leggibile (es. "1b4e28ba-2fa1-11eb-adc1-0242ac120002")
    uuid_unparse(binuuid, str_uuid_dest);
}



typedef int (*operation_handler_t)(int sd, header *head);

int handle_upload(int sd, header *head) {
    char uuid_str[37];
    printf("Upload Ricevuto file: %s (%" PRIu64 " byte)\n", head->namefile, head->length);
    
    if (head->length > MAX_UPLOAD) {
        send_back_msg(sd, SOCKET_ERR);
        return -1;
    }

    //generating new uuid
    generate_new_uuid(uuid_str);
 
    
    int result;
    result = insert_disco(sd, head->length,head->namefile,uuid_str);
    if(result!=0){
        send_back_msg(sd,INSERT_ERR);
        return -1;
    }

    /* 2. ...poi la riga nel database */
    file_record f = {0};
    snprintf(f.uuid, sizeof f.uuid, "%s", uuid_str);
    snprintf(f.name, sizeof f.name, "%s", head->namefile);
    f.size    = (int64_t)head->length;
    f.created = (int64_t)time(NULL);

    if (insert_db(&f) != 0){

        delete_file(uuid_str);
        send_back_msg(sd,INSERT_DB_ERR);
        return -1;
    }
    send_back_msg(sd,SUCCESS_CODE);
    return 0;
}

int handle_download(int sd, header *head) {
    printf("Downloads Richiesto file: %s\n", head->namefile);
    
    file_record f = {0};
    int res=0;
    if((res=find_db(head->namefile,&f))==-1){
        send_back_msg(sd,FIND_DB_ERR);
        return -1;
    }
    if(res==0){
        send_back_msg(sd,DB_NOT_FOUND);
        return -1;
    }
    

    if(send_back_msg(sd,SUCCESS_CODE)!=0) return -1;

    if(find_file(sd,f.uuid)!=0){
        fprintf(stderr, "download di %s interrotto (codice %d)\n", head->namefile, FIND_ERR);
        return -1;
    }    
    
    return 0;
}

int handle_delete(int sd, header *head) {
    printf("Delete Richiesto file: %s\n", head->namefile);
    file_record f = {0};
    int res=0;

     if((res=find_db(head->namefile,&f))==-1){
        send_back_msg(sd,FIND_DB_ERR);
        return -1;
    }
    
    if(res==0){
        send_back_msg(sd,DB_NOT_FOUND);
        return -1;
    }

    if(delete_db(f.uuid)<0){
        send_back_msg(sd,DELETE_ERR);
        return -1;
    }

    if(delete_file(f.uuid)!=0){
        send_back_msg(sd,DELETE_ERR);
        return -1;
    }    
    
    send_back_msg(sd,SUCCESS_CODE);
    return 0;
}

// 4. La Dispatch Table (Il navigatore)

/*
    the only code that IA wrote
    is this Dispatch table but i thought it.
    This is my prompt: Create me a Dispatch table for this code (i put the code before )
*/

typedef struct {
    const char *name;
    operation_handler_t handler;
} command_route_t;

static const command_route_t routes[] = {
    {"UPLOAD",   handle_upload},
    {"DOWNLOAD", handle_download},
    {"DELETE", handle_delete},
    {NULL,       NULL} // Terminatore
};


/*
    steps involved in this functions:
        1) read the header and store it in the struct
        2) understand which operation i have to do
        by dispatching to functor:
        3) find the uuid
        4) use the store.c functions
*/

int handle_connection(int sd,  struct sockaddr_in cliaddr){

    header head;
    char ip[INET_ADDRSTRLEN];
    inet_ntop(AF_INET, &cliaddr.sin_addr, ip, sizeof ip);
    printf("Server (figlio): host client e': %s\n", ip);
        
    if (read_all(sd, &head, sizeof head) != 0) {
        close(sd);
        return SOCKET_ERR;
    }

    /* WE FIX AND ADJUST DATA TO OUR ARCHITECTURE ETC...*/
    head.length = be64toh(head.length);
    head.operation[sizeof head.operation - 1] = '\0';
    head.namefile[sizeof head.namefile - 1] = '\0';

    /* CHECK THE INPUT */
    if(!valid_name(head.namefile)) {
        send_back_msg(sd, SOCKET_ERR);
        close(sd);
        return -1;
    }

    
    // thanks to parser logic and how i created the struct, it's now ready to use
    
    operation_handler_t selected_handler = NULL;
    for (int i = 0; routes[i].name != NULL; i++) {
        if (strcmp(head.operation, routes[i].name) == 0) {
            selected_handler = routes[i].handler;
            break;
        }
    }

    if (selected_handler == NULL) {
        printf("Comando sconosciuto: %s\n", head.operation);
        send_back_msg(sd, SOCKET_ERR);
        close(sd);
       
        return -1;
    }

    
    int rc = selected_handler(sd, &head);

    // Future implementation, To DO:
    /*
        I should create a keep-alive code block 
        to reduce the computational cost of having a three-way handshake everytime, 
        but for this version i keep it simple. 
        I'm gonna do it in later versions.
    */
    close(sd);
  
    return(rc);
}

 
/*
    in the main, we have the daemon where the infinite cycle run
    with the master socket's setting.
    here we are waiting for request from listen_socket
    and handling it with conn_socket
*/

int main(int argc,char **argv){

    int                listen_sd, conn_sd;
    int                port;
    socklen_t          len;
    const int          on = 1;
    struct sockaddr_in cliaddr, servaddr;
    int nread=0;
    char *path="../db/index";
      /* CONTROLLO ARGOMENTI ---------------------------------- */
    if (argc != 2) {
        printf("Error: %s port\n", argv[0]);
        exit(1);
    } else {
        nread = 0;
        while (argv[1][nread] != '\0') {
            if ((argv[1][nread] < '0') || (argv[1][nread] > '9')) {
                printf("La porta deve essere un numero intero\n");
                exit(2);
            }
            nread++;
        }
        port = atoi(argv[1]);
        if (port < 1024 || port > 65535) {
            printf("Porta scorretta...");
            exit(2);
        }
    }

    /* INIZIALIZZAZIONE INDIRIZZO SERVER ----------------------------------------- */
    memset((char *)&servaddr, 0, sizeof(servaddr));
    servaddr.sin_family      = AF_INET;
    servaddr.sin_addr.s_addr = htonl(INADDR_ANY);
    servaddr.sin_port        = htons(port);

    /* CREAZIONE E SETTAGGI SOCKET D'ASCOLTO --------------------------------------- */
    listen_sd = socket(AF_INET, SOCK_STREAM, 0);
    if (listen_sd < 0) {
        perror("creazione socket ");
        exit(1);
    }
    printf("Server: creata la socket d'ascolto per le richieste dei client, fd=%d\n",
           listen_sd);

    if (setsockopt(listen_sd, SOL_SOCKET, SO_REUSEADDR, &on, sizeof(on)) < 0) {
        perror("set opzioni socket d'ascolto");
        exit(1);
    }
    printf("Server: set opzioni socket d'ascolto ok\n");

    if (bind(listen_sd, (struct sockaddr *)&servaddr, sizeof(servaddr)) < 0) {
        perror("bind socket d'ascolto");
        exit(1);
    }
    printf("Server: bind socket d'ascolto ok\n");


    
    if (listen(listen_sd, 128) < 0) // creazione coda d'ascolto
    {
        perror("listen");
        exit(1);
    }
    printf("Server: listen ok\n");

   signal(SIGCHLD, SIG_IGN);
   signal(SIGPIPE, SIG_IGN);

    while(1){

        len = sizeof(cliaddr);
        if ((conn_sd = accept(listen_sd, (struct sockaddr *)&cliaddr, &len)) < 0) {
            /* La accept puo' essere interrotta dai segnali inviati dai figli alla loro
             * teminazione. Tale situazione va gestita opportunamente. Vedere nel man a cosa
             * corrisponde la costante EINTR!*/
            if (errno == EINTR) {
                perror("Forzo la continuazione della accept");
                continue;
            } else
                exit(1);
        }

        // now starts the parallelism 
        pid_t pid=0;
        fflush(stdout);
        if((pid=fork())==0){
            //we don't need it in worker's process
            //so we close it
            
            close(listen_sd);
            
            if((open_db(path))!=0){
                send_back_msg(conn_sd,OPENDB_ERR);
                close(conn_sd);
                exit(1);
            };
            int rc = handle_connection(conn_sd,cliaddr);
            close_db();
            exit(rc == 0 ? 0 : 1);
            
        }else if(pid<0){
            perror("fork");
            close(conn_sd);
            continue;
        }
        close(conn_sd);

    }

    

}