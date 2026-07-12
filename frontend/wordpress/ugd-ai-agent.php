<?php
/**
 * Plugin Name: UGD AI Agent (AskUGD)
 * Description: AskUGD чат виджет на СИТЕ страници (главна, вести, факултети, наука…).
 * Version: 1.1.0
 * Author: UGD
 *
 * ИНСТАЛАЦИЈА (еднократно):
 * 1. Качи ја содржината од frontend/ во: wp-content/uploads/askugd/
 *    (styles.css, dist/custom.js, assets/, …)
 * 2. Копирај го овој фајл во: wp-content/plugins/ugd-ai-agent/ugd-ai-agent.php
 * 3. Активирај го plugin-от во WP Admin → Plugins
 * 4. Исчисти кеш (WP Fastest Cache → Delete Cache)
 */

if (!defined('ABSPATH')) {
    exit;
}

/** Патека до frontend фајловите на серверот. */
define('UGD_AI_AGENT_BASE', content_url('uploads/askugd/'));

/** Backend API — смени на production URL кога API-то е на сервер. */
define('UGD_AI_AGENT_API_URL', 'http://127.0.0.1:8000');

define('UGD_AI_AGENT_VERSION', '10');

/**
 * Директно во wp_footer — најсигурно за site-wide (не зависи од enqueue редослед).
 */
add_action('wp_footer', function (): void {
    static $printed = false;
    if ($printed) {
        return;
    }
    $printed = true;

    $base = trailingslashit(UGD_AI_AGENT_BASE);
    $v = UGD_AI_AGENT_VERSION;
    $api = esc_attr(UGD_AI_AGENT_API_URL);
    $assets_base = esc_attr($base);

    echo '<!-- UGD AI Agent (AskUGD) -->' . "\n";
    printf(
        '<link rel="stylesheet" id="ugd-ai-agent-styles" href="%s" />' . "\n",
        esc_url($base . 'styles.css?v=' . $v)
    );
    printf(
        '<script id="ugd-ai-agent-script" src="%s" data-api-url="%s" data-assets-base="%s" defer></script>' . "\n",
        esc_url($base . 'dist/custom.js?v=' . $v),
        $api,
        $assets_base
    );
    echo '<!-- /UGD AI Agent -->' . "\n";
}, 9999);
