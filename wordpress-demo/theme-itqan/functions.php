<?php
add_action('wp_enqueue_scripts', function(){ wp_enqueue_style('itqan', get_stylesheet_directory_uri().'/assets/site.css', [], '1.0'); });
add_action('init', function(){ global $wp_locale; if ($wp_locale) $wp_locale->text_direction = 'rtl'; });
add_filter('language_attributes', fn() => 'lang="ar" dir="rtl"');
