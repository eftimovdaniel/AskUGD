<?php
/**
 * Must-Use plugin: UGD AI Agent (AskUGD) — се активира автоматски.
 *
 * Копирај го овој фајл во: wp-content/mu-plugins/ugd-ai-agent.php
 * (креирај ја папката mu-plugins ако не постои)
 *
 * Фајловите мора да се во: wp-content/uploads/askugd/
 */

if (!defined('ABSPATH')) {
    exit;
}

define('UGD_AI_AGENT_BASE', content_url('uploads/askugd/'));
define('UGD_AI_AGENT_API_URL', 'http://127.0.0.1:8000');
define('UGD_AI_AGENT_VERSION', '10');

add_action('wp_footer', function (): void {
    static $printed = false;
    if ($printed) {
        return;
    }
    $printed = true;

    $base = trailingslashit(UGD_AI_AGENT_BASE);
    $v = UGD_AI_AGENT_VERSION;

    echo '<!-- UGD AI Agent (AskUGD) -->' . "\n";
    printf(
        '<link rel="stylesheet" id="ugd-ai-agent-styles" href="%s" />' . "\n",
        esc_url($base . 'styles.css?v=' . $v)
    );
    printf(
        '<script id="ugd-ai-agent-script" src="%s" data-api-url="%s" data-assets-base="%s" defer></script>' . "\n",
        esc_url($base . 'dist/custom.js?v=' . $v),
        esc_attr(UGD_AI_AGENT_API_URL),
        esc_attr($base)
    );
    echo '<!-- /UGD AI Agent -->' . "\n";
}, 9999);
