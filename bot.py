
    await init_http_session()
    init_cache(ttl=CACHE_TTL)
    init_rate_limiter(max_requests=RATE_LIMIT_REQUESTS, window_secs=RATE_LIMIT_WINDOW)
    init_queue(max_global=MAX_CONCURRENT_DOWNLOADS, max_per_user=MAX_CONCURRENT_PER_USER)

    tracker = init_stats()
    await tracker.load()

    # â”€â”€ طھط´ط؛ظٹظ„ ط§ظ„ظ…ظ‡ط§ظ… ط§ظ„ط®ظ„ظپظٹط© â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    loop = asyncio.get_event_loop()
    loop.create_task(_cache_cleanup_loop(),                  name="cache-cleanup")
    loop.create_task(_pending_cleanup_loop(application),     name="pending-cleanup")
    loop.create_task(_stats_autosave_loop(),                 name="stats-autosave")
    loop.create_task(_self_keepalive_loop(),                 name="self-keepalive")   # Layer 5

    # â”€â”€ Layer 4: ط®ط§ط¯ظ… HTTP â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    cfg.BOT_START_TIME = time.time()
    try:
        runner = await start_uptime_server(port=HEALTH_PORT)
        application.bot_data["uptime_runner"] = runner
        logger.info(
            "ًںŒگ ط®ط§ط¯ظ… ط§ظ„طµط­ط© ط¹ظ„ظ‰ ط§ظ„ظ…ظ†ظپط° %d â†’ UptimeRobot: ط£ط¶ظپ /ping ظ„ظ…ط±ط§ظ‚ط¨طھظƒ",
            HEALTH_PORT,
        )
    except Exception as exc:
        logger.warning("طھط¹ط°ظ‘ط± طھط´ط؛ظٹظ„ ط®ط§ط¯ظ… ط§ظ„طµط­ط©: %s", exc)

    set_running(True)
    logger.info("âœ… ط¬ظ…ظٹط¹ ط§ظ„ط®ط¯ظ…ط§طھ ط¬ط§ظ‡ط²ط©.")


async def _post_shutdown(application: Application) -> None:
    """ظٹظڈط؛ظ„ظ‚ ط§ظ„ظ…ظˆط§ط±ط¯ ظˆظٹط­ظپط¸ ط§ظ„ط¨ظٹط§ظ†ط§طھ ط¹ظ†ط¯ ط§ظ„ط¥ظٹظ‚ط§ظپ."""
    logger.info("ط¬ط§ط±ظٹ ط§ظ„ط¥ط؛ظ„ط§ظ‚ ط§ظ„ظ†ط¸ظٹظپ...")
    set_running(False)

    from services.stats import get_stats
    try:
        await get_stats().save()
    except Exception:
        logger.exception("ظپط´ظ„ ط­ظپط¸ ط§ظ„ط¥ط­طµط§ط¦ظٹط§طھ.")

    await close_http_session()

    runner = application.bot_data.get("uptime_runner")
    if runner:
        await stop_uptime_server(runner)

    logger.info("âœ… طھظ… ط§ظ„ط¥ط؛ظ„ط§ظ‚ ط§ظ„ظ†ط¸ظٹظپ.")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# ط¨ظ†ط§ط، ط§ظ„طھط·ط¨ظٹظ‚
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _build_app() -> Application:
    """
    ظٹط¨ظ†ظٹ Application ط¨ط¥ط¹ط¯ط§ط¯ط§طھ PTB ط§ظ„ظ…ظڈط­ط³ظژظ‘ظ†ط© ظ„ظ„ط§ط³طھظ‚ط±ط§ط±:
      â€¢ timeouts: 30s ظ„ظƒظ„ ط¹ظ…ظ„ظٹط©
      â€¢ connection_pool_size: 8 ط§طھطµط§ظ„ط§طھ ظ…طھط²ط§ظ…ظ†ط©
      â€¢ get_updates_*: timeout ظ…ط³طھظ‚ظ„ ظ„ظ€ polling
    """
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        # â”€â”€ Timeouts ط§طھطµط§ظ„ HTTP â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        .connect_timeout(_CONNECT_TIMEOUT)
        .read_timeout(_READ_TIMEOUT)
        .write_timeout(_WRITE_TIMEOUT)
        .pool_timeout(_POOL_TIMEOUT)
        .connection_pool_size(_POOL_SIZE)
        # â”€â”€ Timeouts polling (get_updates) ظ…ط³طھظ‚ظ„ط© â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        .get_updates_connect_timeout(_CONNECT_TIMEOUT)
        .get_updates_read_timeout(60.0)   # polling ظٹط­طھط§ط¬ ظˆظ‚طھط§ظ‹ ط£ط·ظˆظ„
        .get_updates_write_timeout(_WRITE_TIMEOUT)
        .get_updates_pool_timeout(_POOL_TIMEOUT)
        # â”€â”€ Hooks ط¯ظˆط±ط© ط§ظ„ط­ظٹط§ط© â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        # â”€â”€ طھظپط¹ظٹظ„ ط§ظ„طھط­ط¯ظٹط«ط§طھ ط§ظ„ظ…طھط²ط§ظ…ظ†ط© â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        .concurrent_updates(True)
        .build()
    )

    # â”€â”€ ط§ط®طھظٹط§ط± ظ†ظˆط¹ ط§ظ„ظˆط³ط§ط¦ط· â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    app.add_handler(CommandHandler("start",      start_command))
    app.add_handler(CommandHandler("setchannel", setchannel_command))
    app.add_handler(CommandHandler("forcejoin",  forcejoin_command))
    app.add_handler(CommandHandler("stats",      stats_command))

    app.add_handler(CallbackQueryHandler(download_video_callback, pattern=r"^dl_video:"))
    app.add_handler(CallbackQueryHandler(download_audio_callback, pattern=r"^dl_audio:"))

    # â”€â”€ ط§ظ„ط¯ظپط¹ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    app.add_handler(CallbackQueryHandler(pay_once_callback,    pattern=r"^pay_once:"))
    app.add_handler(CallbackQueryHandler(pay_weekly_callback,  pattern=r"^pay_weekly:"))
    app.add_handler(CallbackQueryHandler(pay_monthly_callback, pattern=r"^pay_monthly:"))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout_query_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))

    # â”€â”€ ط§ظ„ط£ط²ط±ط§ط± ط§ظ„ط£ط®ط±ظ‰ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    app.add_handler(CallbackQueryHandler(check_subscription_callback, pattern="^check_subscription$"))
    app.add_handler(CallbackQueryHandler(share_bot_callback,          pattern="^share_bot$"))
    app.add_handler(CallbackQueryHandler(refresh_stats_callback,      pattern="^refresh_stats$"))

    # â”€â”€ ط§ظ„ظƒظ„ظ…ط§طھ ط§ظ„ظ…ظپطھط§ط­ظٹط© ظ„ظ„ظ…ط´ط±ظپ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    _stats_filter = filters.TEXT & ~filters.COMMAND & filters.Regex(
        r"^(ط¥ط­طµط§ط¦ظٹط§طھ|ط§ط­طµط§ط¦ظٹط§طھ|stats|ط§ظ„ط¥ط­طµط§ط¦ظٹط§طھ)$"
    )
    app.add_handler(MessageHandler(_stats_filter, stats_keyword_handler))

    # â”€â”€ ط§ظ„ط±ط³ط§ط¦ظ„ ط§ظ„ظ†طµظٹط© â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # â”€â”€ ظ…ط¹ط§ظ„ط¬ ط§ظ„ط£ط®ط·ط§ط، â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    app.add_error_handler(error_handler)

    return app


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Layer 1: Python Watchdog
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_shutdown_requested = False


def _handle_signal(signum: int, frame) -> None:
    """ظ…ط¹ط§ظ„ط¬ ط¥ط´ط§ط±ط§طھ SIGTERM/SIGINT ظ„ظ„ط¥ظٹظ‚ط§ظپ ط§ظ„ظ†ط¸ظٹظپ."""
    global _shutdown_requested
    sig_name = signal.Signals(signum).name
    logger.info("ًں“، ط§ط³طھظڈظ‚ط¨ظ„طھ ط¥ط´ط§ط±ط© %s â€” ط¨ط¯ط، ط§ظ„ط¥ظٹظ‚ط§ظپ ط§ظ„ظ†ط¸ظٹظپ...", sig_name)
    _shutdown_requested = True


def main() -> None:
    """
    ظ†ظ‚ط·ط© ط§ظ„ط¯ط®ظˆظ„ ط§ظ„ط±ط¦ظٹط³ظٹط© ظ…ط¹ Python watchdog.

    طھط³ظ„ط³ظ„ ط§ظ„ط§ط³طھظ‚ط±ط§ط±:
      1. طھط³ط¬ظٹظ„ ظ…ط¹ط§ظ„ط¬ط§طھ SIGTERM/SIGINT
      2. ط¨ظ†ط§ط، Application ط¨ط¥ط¹ط¯ط§ط¯ط§طھ PTB ط§ظ„ظ…ظڈط­ط³ظژظ‘ظ†ط©
      3. run_polling ظ…ط¹ ط¥ط¹ط§ط¯ط© طھط´ط؛ظٹظ„ طھظ„ظ‚ط§ط¦ظٹط© ط¹ظ†ط¯ ط§ظ„ط§ظ†ظ‡ظٹط§ط±
      4. طھط£ط®ظٹط± ط¨ظٹظ† ط§ظ„ظ…ط­ط§ظˆظ„ط§طھ ظ„ظ…ظ†ط¹ CPU spike
    """
    # â”€â”€ طھط³ط¬ظٹظ„ ظ…ط¹ط§ظ„ط¬ط§طھ ط§ظ„ط¥ط´ط§ط±ط© â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    logger.info("â•گ" * 55)
    logger.info("  ZenDown Bot ظٹط¨ط¯ط£")
    logger.info("  Layer 1: Python Watchdog (%d ظ…ط­ط§ظˆظ„ط© | delay=%ds)", _MAX_RESTARTS, _RESTART_DELAY)
    logger.info("  Layer 2: Shell Watchdog  (start.sh)")
    logger.info("  Layer 3: Replit Workflow auto-restart")
    logger.info("  Layer 4: HTTP /health /ping (port %d)", HEALTH_PORT)
    logger.info("  Layer 5: Self-Keepalive (ظƒظ„ %ds)", _KEEPALIVE_SECS)
    logger.info("â•گ" * 55)

    for attempt in range(1, _MAX_RESTARTS + 1):
        if _shutdown_requested:
            logger.info("ط¥ظٹظ‚ط§ظپ ظ†ط¸ظٹظپ ظ…ط·ظ„ظˆط¨ â€” ط®ط±ظˆط¬.")
            break

        logger.info("â–¶ ظ…ط­ط§ظˆظ„ط© %d/%d", attempt, _MAX_RESTARTS)
        t_start = time.monotonic()

        try:
            app = _build_app()
            app.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
                close_loop=False,
            )
            logger.info("âœ… ط§ظ„ط¨ظˆطھ ط£ظڈظˆظ‚ظپ ط¨ط´ظƒظ„ ظ†ط¸ظٹظپ.")
            break

        except KeyboardInterrupt:
            logger.info("âŒ¨ï¸ڈ  Ctrl+C â€” ط¥ظٹظ‚ط§ظپ ظٹط¯ظˆظٹ.")
            break

        except SystemExit as exc:
            if exc.code == 0:
                logger.info("âœ… SystemExit(0) â€” ط®ط±ظˆط¬ ظ†ط¸ظٹظپ.")
                break
            logger.warning("SystemExit(%s) â€” ظ‚ط¯ ظٹظڈط¹ط§ط¯ ط§ظ„طھط´ط؛ظٹظ„.", exc.code)

        except Exception as exc:
            runtime = time.monotonic() - t_start
            record_error()
            logger.error(
                "â‌Œ ط§ظ†ظ‡ظٹط§ط± ط¨ط¹ط¯ %.1fs (ظ…ط­ط§ظˆظ„ط© %d): %s",
                runtime, attempt, exc, exc_info=True,
            )

        if attempt < _MAX_RESTARTS and not _shutdown_requested:
            logger.info("âڈ³ ط¥ط¹ط§ط¯ط© ط®ظ„ط§ظ„ %ds...", _RESTART_DELAY)
            time.sleep(_RESTART_DELAY)

    logger.info("â•گ" * 55)
    logger.info("  ZenDown Bot ط£ظڈظˆظ‚ظپ â€” sys.exit(0)")
    logger.info("â•گ" * 55)
    sys.exit(0)


if __name__ == "__main__":
    main()
