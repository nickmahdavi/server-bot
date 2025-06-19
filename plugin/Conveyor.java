package com.khazix.conveyor;

import com.google.inject.Inject;
import com.velocitypowered.api.event.Subscribe;
import com.velocitypowered.api.event.connection.DisconnectEvent;
import com.velocitypowered.api.event.player.ServerConnectedEvent;
import com.velocitypowered.api.plugin.Plugin;
import com.velocitypowered.api.proxy.Player;
import com.velocitypowered.api.proxy.ProxyServer;
import com.velocitypowered.api.proxy.ServerConnection;
import com.velocitypowered.api.proxy.server.RegisteredServer;
import com.velocitypowered.api.scheduler.ScheduledTask;

import org.slf4j.Logger;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Collection;
import java.util.concurrent.CompletableFuture;
import java.util.NoSuchElementException;


@Plugin(id = "conveyor", name = "Conveyor", version = "1.0-SNAPSHOT", description = "Move players automatically to the main server", authors = {"nick"})

public class Conveyor {
    private final ProxyServer server;
    private final Logger logger;
    private ScheduledTask checkTask;
    private ScheduledTask shutdownTask;

    private final HttpClient httpClient = HttpClient.newHttpClient();

    @Inject
    public Conveyor(ProxyServer server, Logger logger) {
        this.server = server;
        this.logger = logger;
        logger.info("Conveyor plugin loaded!");
    }

    private CompletableFuture<Boolean> post(String path) {
        HttpRequest request = HttpRequest.newBuilder()
            .uri(URI.create("http://localhost:8080" + path))
            .timeout(Duration.ofSeconds(5))
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.noBody())
            .build();

        return httpClient.sendAsync(request, HttpResponse.BodyHandlers.discarding())
            .thenApply(response -> response.statusCode() == 200)
            .exceptionally(e -> {
                logger.error("Error sending POST request: " + e.getMessage());
                return false;
            });
    }
    
    private CompletableFuture<Boolean> mainServerOnline() {
        return post("/status");
        // 202: instance up but server unreachable
        // 503: instance down
    }

    private CompletableFuture<Boolean> startServer() {
        return post("/start");
        // endpoint <- asyncio.create_task; no significant delay
    }

    private CompletableFuture<Boolean> stopServer() {
        return post("/stop");
    }
    
    @Subscribe
    public void onServerConnected(ServerConnectedEvent event) {
        if (shutdownTask != null && shutdownTask.status() == ScheduledTask.TaskStatus.RUNNING) {
            shutdownTask.cancel();
        }

        if (!event.getServer().getServerInfo().getName().equals("limbo")) {
            return;
        }

        // Player was automatically placed in limbo, so server is not online

        if (checkTask == null || checkTask.status() != ScheduledTask.TaskStatus.RUNNING) {
            this.startServer();

            checkTask = server.getScheduler().buildTask(this, () -> {
                mainServerOnline().thenAccept(online -> {
                    if (online) {
                        RegisteredServer mainServer = server.getServer("main").orElseThrow(() -> new NoSuchElementException("Main server not found"));
                        RegisteredServer limboServer = server.getServer("limbo").orElseThrow(() -> new NoSuchElementException("Limbo server not found"));

                        limboServer.getPlayersConnected().forEach(player -> { player.createConnectionRequest(mainServer).fireAndForget(); });

                        checkTask.cancel();
                    }
                });

            }).repeat(Duration.ofSeconds(3)).schedule();
        }
    }

    @Subscribe
    public void onDisconnect(DisconnectEvent event) {
        RegisteredServer previousServer = event.getPlayer()
            .getCurrentServer()
            .orElseThrow(() -> new NoSuchElementException("Player not connected to any server"))
            .getServer();

        if (!previousServer.getServerInfo().getName().equals("main")) {
            return;
        }

        server.getScheduler().buildTask(this, () -> {
            int playerCount = previousServer.getPlayersConnected().size();
            if (playerCount == 0) {
                if (shutdownTask == null || shutdownTask.status() != ScheduledTask.TaskStatus.RUNNING) {
                    shutdownTask = server.getScheduler().buildTask(this, () -> {
                        this.stopServer();
                        shutdownTask.cancel();
                    }).delay(Duration.ofSeconds(1800)).schedule();
                }
            }
        }).schedule();
    }
}