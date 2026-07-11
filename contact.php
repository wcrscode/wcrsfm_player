<?php
/**
 * Contact form handler
 * Spam protection: honeypot field, minimum form-open time, per-IP rate limiting,
 * input validation, and email-header-injection sanitization.
 * Requires PHPMailer — install with: composer install
 */

header('Content-Type: application/json');
header('X-Content-Type-Options: nosniff');

require_once __DIR__ . '/mail_config.php';
require_once __DIR__ . '/vendor/autoload.php';

use PHPMailer\PHPMailer\PHPMailer;
use PHPMailer\PHPMailer\Exception;

// ── helpers ──────────────────────────────────────────────────────────────────

function respond(bool $success, string $message, int $status = 200): void
{
    http_response_code($status);
    echo json_encode(['success' => $success, 'message' => $message]);
    exit;
}

// ── method guard ─────────────────────────────────────────────────────────────

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    respond(false, 'Method not allowed.', 405);
}

// ── honeypot ─────────────────────────────────────────────────────────────────
// A hidden field called "website" — humans leave it blank, bots fill it.
// Return a fake success so bots think they succeeded.

if (!empty($_POST['website'])) {
    respond(true, 'Your message was sent. We will reach out to you soon.');
}

// ── minimum form-open time ───────────────────────────────────────────────────
// JS records a Unix timestamp when the page loads; bots submit almost instantly.

$loadTime = filter_input(INPUT_POST, 'load_time', FILTER_VALIDATE_INT) ?: 0;
if ($loadTime === 0 || (time() - $loadTime) < MIN_FORM_TIME) {
    respond(false, 'Please take a moment before submitting.', 400);
}

// ── per-IP rate limiting ─────────────────────────────────────────────────────
// Stores submission timestamps in data/rate_limit.json (not web-accessible).

$ip          = $_SERVER['HTTP_X_FORWARDED_FOR'] ?? $_SERVER['REMOTE_ADDR'] ?? 'unknown';
$ip          = trim(explode(',', $ip)[0]); // use first IP if behind a proxy
$dataDir     = __DIR__ . '/data';
$rateFile    = $dataDir . '/rate_limit.json';
$rateData    = [];

if (is_readable($rateFile)) {
    $rateData = json_decode(file_get_contents($rateFile), true) ?? [];
}

// Purge entries older than one hour
$oneHourAgo = time() - 3600;
foreach ($rateData as $storedIp => $timestamps) {
    $rateData[$storedIp] = array_values(array_filter($timestamps, fn($t) => $t > $oneHourAgo));
    if (empty($rateData[$storedIp])) {
        unset($rateData[$storedIp]);
    }
}

if (count($rateData[$ip] ?? []) >= RATE_LIMIT_MAX) {
    respond(false, 'Too many messages sent recently. Please try again later.', 429);
}

// ── input validation ─────────────────────────────────────────────────────────

$name    = trim($_POST['name']    ?? '');
$email   = trim($_POST['email']   ?? '');
$subject = trim($_POST['subject'] ?? '');
$message = trim($_POST['message'] ?? '');

$errors = [];

if ($name === '')                              $errors[] = 'Name is required.';
if (strlen($name) > 100)                      $errors[] = 'Name must be 100 characters or fewer.';
if ($email === '')                             $errors[] = 'Email is required.';
if (!filter_var($email, FILTER_VALIDATE_EMAIL)) $errors[] = 'Please enter a valid email address.';
if (strlen($email) > 200)                     $errors[] = 'Email address is too long.';
if ($message === '')                           $errors[] = 'Message is required.';
if (strlen($message) > 2000)                  $errors[] = 'Message must be 2,000 characters or fewer.';
if (strlen($subject) > 200)                   $errors[] = 'Subject must be 200 characters or fewer.';

if (!empty($errors)) {
    respond(false, implode(' ', $errors), 400);
}

// ── sanitize against header injection ────────────────────────────────────────

$name    = str_replace(["\r", "\n", '%0a', '%0d'], ' ', $name);
$subject = str_replace(["\r", "\n", '%0a', '%0d'], ' ', $subject);
$email   = filter_var($email, FILTER_SANITIZE_EMAIL);

if ($subject === '') {
    $subject = 'Message from the WCRS FM website';
}

// ── send via PHPMailer ───────────────────────────────────────────────────────

$mail = new PHPMailer(true);

try {
    $mail->isSMTP();
    $mail->Host       = SMTP_HOST;
    $mail->SMTPAuth   = true;
    $mail->Username   = SMTP_USER;
    $mail->Password   = SMTP_PASS;
    $mail->SMTPSecure = SMTP_SECURE === 'ssl' ? PHPMailer::ENCRYPTION_SMTPS : PHPMailer::ENCRYPTION_STARTTLS;
    $mail->Port       = SMTP_PORT;

    $mail->setFrom(MAIL_FROM, MAIL_FROM_NAME);
    $mail->addAddress(MAIL_TO);
    $mail->addReplyTo($email, $name);

    $mail->Subject = 'WCRS Contact: ' . $subject;

    $bodyText = "Name:    $name\nEmail:   $email\nSubject: $subject\n\nMessage:\n$message";
    $bodyHtml = nl2br(htmlspecialchars($bodyText, ENT_QUOTES, 'UTF-8'));

    $mail->isHTML(true);
    $mail->Body    = "<pre style=\"font-family:sans-serif;\">$bodyHtml</pre>";
    $mail->AltBody = $bodyText;

    $mail->send();

    // Record this submission for rate limiting
    $rateData[$ip][] = time();
    if (!is_dir($dataDir)) {
        mkdir($dataDir, 0750, true);
    }
    file_put_contents($rateFile, json_encode($rateData), LOCK_EX);

    respond(true, 'Your message was sent. We will reach out to you soon.');

} catch (Exception $e) {
    // Log internally but don't expose SMTP details to the client
    error_log('PHPMailer error: ' . $mail->ErrorInfo);
    respond(false, 'Sorry, the message could not be sent. Please try again later.', 500);
}
