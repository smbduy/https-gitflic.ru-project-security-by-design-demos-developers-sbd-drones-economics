package tests

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"net"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/segmentio/kafka-go"
)

const (
	defaultKafkaReadTimeout = 45 * time.Second
	defaultDialTimeout      = 2 * time.Second
	defaultCoverageAmount   = 5000000.00
)

func TestCalculationRequest(t *testing.T) {
	fx := newKafkaFixture(t)
	requestID := uniqueID("req-calc")
	orderID := uniqueID("order-calc")

	request := map[string]any{
		"request_id":      requestID,
		"order_id":        orderID,
		"manufacturer_id": uniqueID("manufacturer"),
		"operator_id":     uniqueID("operator"),
		"drone_id":        uniqueID("drone"),
		"security_goals":  []string{"ЦБ1", "ЦБ2"},
		"coverage_amount": defaultCoverageAmount,
		"calculation_id":  uniqueID("calc"),
		"incident":        nil,
		"request_type":    "CALCULATION",
	}

	response := fx.sendAndReadResponse(t, request)

	assertEqualStringField(t, response, "request_id", requestID)
	assertEqualStringField(t, response, "order_id", orderID)
	assertEqualStringField(t, response, "status", "SUCCESS")
	assertNonEmptyStringField(t, response, "response_id")
	assertPositiveNumberField(t, response, "calculated_cost")
	assertPositiveNumberField(t, response, "manufacturer_kbm")
	assertPositiveNumberField(t, response, "operator_kbm")
}

func TestPurchaseAndTerminationLifecycle(t *testing.T) {
	fx := newKafkaFixture(t)
	orderID := uniqueID("order-purchase")

	purchaseRequestID := uniqueID("req-purchase")
	purchaseRequest := map[string]any{
		"request_id":      purchaseRequestID,
		"order_id":        orderID,
		"manufacturer_id": uniqueID("manufacturer"),
		"operator_id":     uniqueID("operator"),
		"drone_id":        uniqueID("drone"),
		"security_goals":  []string{"ЦБ1", "ЦБ2"},
		"coverage_amount": defaultCoverageAmount,
		"calculation_id":  uniqueID("calc-purchase"),
		"incident":        nil,
		"request_type":    "PURCHASE",
	}

	purchaseResponse := fx.sendAndReadResponse(t, purchaseRequest)

	assertEqualStringField(t, purchaseResponse, "request_id", purchaseRequestID)
	assertEqualStringField(t, purchaseResponse, "order_id", orderID)
	assertEqualStringField(t, purchaseResponse, "status", "SUCCESS")
	assertNonEmptyStringField(t, purchaseResponse, "policy_id")
	assertPositiveNumberField(t, purchaseResponse, "calculated_cost")

	terminationRequestID := uniqueID("req-termination")
	terminationRequest := map[string]any{
		"request_id":      terminationRequestID,
		"order_id":        orderID,
		"manufacturer_id": uniqueID("manufacturer"),
		"operator_id":     uniqueID("operator"),
		"drone_id":        uniqueID("drone"),
		"security_goals":  []string{"ЦБ1", "ЦБ2"},
		"coverage_amount": defaultCoverageAmount,
		"calculation_id":  nil,
		"incident":        nil,
		"request_type":    "POLICY_TERMINATION",
	}

	terminationResponse := fx.sendAndReadResponse(t, terminationRequest)

	assertEqualStringField(t, terminationResponse, "request_id", terminationRequestID)
	assertEqualStringField(t, terminationResponse, "order_id", orderID)
	assertEqualStringField(t, terminationResponse, "status", "SUCCESS")
}

func TestIncidentRequestSuccess(t *testing.T) {
	fx := newKafkaFixture(t)
	requestID := uniqueID("req-incident")
	orderID := uniqueID("order-incident")

	request := map[string]any{
		"request_id":      requestID,
		"order_id":        orderID,
		"manufacturer_id": uniqueID("manufacturer"),
		"operator_id":     uniqueID("operator"),
		"drone_id":        uniqueID("drone"),
		"security_goals":  []string{"ЦБ1", "ЦБ2"},
		"coverage_amount": defaultCoverageAmount,
		"calculation_id":  nil,
		"request_type":    "INCIDENT",
		"incident": map[string]any{
			"incident_id":   uniqueID("incident"),
			"order_id":      orderID,
			"policy_id":     uniqueID("policy"),
			"damage_amount": 17350.75,
			"incident_date": time.Now().UTC().Format("2006-01-02T15:04:05"),
			"status":        "REPORTED",
		},
	}

	response := fx.sendAndReadResponse(t, request)

	assertEqualStringField(t, response, "request_id", requestID)
	assertEqualStringField(t, response, "order_id", orderID)
	assertEqualStringField(t, response, "status", "SUCCESS")
	assertPositiveNumberField(t, response, "coverage_amount")
	assertPositiveNumberField(t, response, "payment_amount")
	assertPositiveNumberField(t, response, "new_manufacturer_kbm")
	assertPositiveNumberField(t, response, "new_operator_kbm")
}

func TestIncidentValidationError(t *testing.T) {
	fx := newKafkaFixture(t)
	requestID := uniqueID("req-incident-error")

	request := map[string]any{
		"request_id":      requestID,
		"order_id":        uniqueID("order-incident-error"),
		"manufacturer_id": uniqueID("manufacturer"),
		"operator_id":     uniqueID("operator"),
		"drone_id":        uniqueID("drone"),
		"security_goals":  []string{"ЦБ1", "ЦБ2"},
		"coverage_amount": defaultCoverageAmount,
		"calculation_id":  nil,
		"request_type":    "INCIDENT",
		"incident":        nil,
	}

	response := fx.sendAndReadResponse(t, request)

	assertEqualStringField(t, response, "request_id", requestID)
	assertEqualStringField(t, response, "status", "FAILED")

	message := getStringField(t, response, "message")
	if !strings.Contains(message, "Incident data is missing") {
		t.Fatalf("unexpected error message: %q", message)
	}
}

func TestTerminationForUnknownOrder(t *testing.T) {
	fx := newKafkaFixture(t)
	requestID := uniqueID("req-termination-missing")

	request := map[string]any{
		"request_id":      requestID,
		"order_id":        uniqueID("missing-order"),
		"manufacturer_id": uniqueID("manufacturer"),
		"operator_id":     uniqueID("operator"),
		"drone_id":        uniqueID("drone"),
		"security_goals":  []string{"ЦБ1", "ЦБ2"},
		"coverage_amount": defaultCoverageAmount,
		"calculation_id":  nil,
		"incident":        nil,
		"request_type":    "POLICY_TERMINATION",
	}

	response := fx.sendAndReadResponse(t, request)

	assertEqualStringField(t, response, "request_id", requestID)
	assertEqualStringField(t, response, "status", "FAILED")
}

type kafkaFixture struct {
	brokers       []string
	requestTopic  string
	responseTopic string
}

func newKafkaFixture(t *testing.T) kafkaFixture {
	t.Helper()

	brokers := resolveKafkaBrokers()
	requestTopic, responseTopic := resolveTopics()

	waitForKafkaReady(t, brokers)

	return kafkaFixture{
		brokers:       brokers,
		requestTopic:  requestTopic,
		responseTopic: responseTopic,
	}
}

func (f kafkaFixture) sendAndReadResponse(t *testing.T, request map[string]any) map[string]any {
	t.Helper()

	requestID := getStringField(t, request, "request_id")

	reader := kafka.NewReader(kafka.ReaderConfig{
		Brokers:     f.brokers,
		Topic:       f.responseTopic,
		GroupID:     uniqueID("tests-response-reader"),
		MinBytes:    1,
		MaxBytes:    10e6,
		StartOffset: kafka.FirstOffset,
	})
	defer func() {
		if err := reader.Close(); err != nil {
			t.Fatalf("failed to close kafka reader: %v", err)
		}
	}()

	writer := &kafka.Writer{
		Addr:         kafka.TCP(f.brokers...),
		Topic:        f.requestTopic,
		Balancer:     &kafka.LeastBytes{},
		RequiredAcks: kafka.RequireAll,
	}
	defer func() {
		if err := writer.Close(); err != nil {
			t.Fatalf("failed to close kafka writer: %v", err)
		}
	}()

	payload, err := json.Marshal(request)
	if err != nil {
		t.Fatalf("failed to marshal request payload: %v", err)
	}

	writeCtx, cancelWrite := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancelWrite()

	err = writer.WriteMessages(writeCtx, kafka.Message{
		Key:   []byte(requestID),
		Value: payload,
	})
	if err != nil {
		t.Fatalf("failed to send kafka message to topic %q: %v", f.requestTopic, err)
	}

	readCtx, cancelRead := context.WithTimeout(context.Background(), defaultKafkaReadTimeout)
	defer cancelRead()

	for {
		msg, err := reader.ReadMessage(readCtx)
		if err != nil {
			t.Fatalf("failed to read kafka response from topic %q: %v", f.responseTopic, err)
		}

		var response map[string]any
		if err := json.Unmarshal(msg.Value, &response); err != nil {
			continue
		}

		if getStringFieldNoFail(response, "request_id") != requestID {
			continue
		}

		return response
	}
}

func resolveKafkaBrokers() []string {
	if fromEnv := strings.TrimSpace(os.Getenv("KAFKA_BROKERS")); fromEnv != "" {
		parts := strings.Split(fromEnv, ",")
		brokers := make([]string, 0, len(parts))
		for _, p := range parts {
			candidate := strings.TrimSpace(p)
			if candidate != "" {
				brokers = append(brokers, candidate)
			}
		}
		if len(brokers) > 0 {
			return brokers
		}
	}

	return []string{"kafka:29092", "localhost:9092"}
}

func resolveTopics() (requestTopic string, responseTopic string) {
	if req := strings.TrimSpace(os.Getenv("INSURANCE_REQUEST_TOPIC")); req != "" {
		requestTopic = req
	}
	if resp := strings.TrimSpace(os.Getenv("INSURANCE_RESPONSE_TOPIC")); resp != "" {
		responseTopic = resp
	}

	if requestTopic != "" && responseTopic != "" {
		return requestTopic, responseTopic
	}

	instanceID := strings.TrimSpace(os.Getenv("INSURER_INSTANCE_ID"))
	if instanceID == "" {
		instanceID = strings.TrimSpace(os.Getenv("INSTANCE_ID"))
	}
	if instanceID == "" {
		instanceID = "1"
	}

	if requestTopic == "" {
		requestTopic = fmt.Sprintf("v1.%s.%s.%s.requests", "Insurer", instanceID, "insurer-service")
	}
	if responseTopic == "" {
		responseTopic = fmt.Sprintf("v1.%s.%s.%s.responses", "Insurer", instanceID, "insurer-service")
	}

	return requestTopic, responseTopic
}

func waitForKafkaReady(t *testing.T, brokers []string) {
	t.Helper()

	deadline := time.Now().Add(90 * time.Second)
	for time.Now().Before(deadline) {
		for _, broker := range brokers {
			conn, err := net.DialTimeout("tcp", broker, defaultDialTimeout)
			if err == nil {
				_ = conn.Close()
				return
			}
		}
		time.Sleep(time.Second)
	}

	t.Fatalf("kafka is unreachable, checked brokers: %v", brokers)
}

func assertEqualStringField(t *testing.T, payload map[string]any, field, expected string) {
	t.Helper()

	actual := getStringField(t, payload, field)
	if actual != expected {
		t.Fatalf("unexpected %s: got %q, want %q", field, actual, expected)
	}
}

func assertNonEmptyStringField(t *testing.T, payload map[string]any, field string) {
	t.Helper()

	value := getStringField(t, payload, field)
	if strings.TrimSpace(value) == "" {
		t.Fatalf("%s should not be empty", field)
	}
}

func assertPositiveNumberField(t *testing.T, payload map[string]any, field string) {
	t.Helper()

	value := getNumberField(t, payload, field)
	if value <= 0 {
		t.Fatalf("%s should be positive, got %v", field, value)
	}
}

func getStringField(t *testing.T, payload map[string]any, field string) string {
	t.Helper()

	value, ok := payload[field]
	if !ok {
		t.Fatalf("response is missing field %q", field)
	}

	asString, ok := value.(string)
	if !ok {
		t.Fatalf("field %q is not a string: %#v", field, value)
	}

	return asString
}

func getStringFieldNoFail(payload map[string]any, field string) string {
	value, ok := payload[field]
	if !ok {
		return ""
	}
	asString, ok := value.(string)
	if !ok {
		return ""
	}
	return asString
}

func getNumberField(t *testing.T, payload map[string]any, field string) float64 {
	t.Helper()

	value, ok := payload[field]
	if !ok {
		t.Fatalf("response is missing field %q", field)
	}

	asNumber, ok := value.(float64)
	if !ok || math.IsNaN(asNumber) || math.IsInf(asNumber, 0) {
		t.Fatalf("field %q is not a valid number: %#v", field, value)
	}

	return asNumber
}

func uniqueID(prefix string) string {
	return fmt.Sprintf("%s-%d", prefix, time.Now().UnixNano())
}
