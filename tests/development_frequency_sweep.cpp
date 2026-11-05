// SPDX-License-Identifier: MIT
#include <SoapySDR/Device.hpp>
#include <SoapySDR/Formats.hpp>
#include <algorithm>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include <chrono>
#include <cmath>
#include <complex>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#include <linux/rp1_gpclk.h>

namespace {
constexpr long double kNominalParentHz = 200000000.0L;
constexpr double kMaximumDirectHz = 100000000.0;
constexpr uint32_t kDitherPeriod = 66792U;
constexpr double kMinimumHz = 135700.0;
constexpr double kMaximumHz = 148000000.0;
constexpr unsigned kDefaultPoints = 16;
constexpr double kSampleRate = 250000.0;
constexpr double kTuneOffsetHz = 100000.0;
constexpr uint64_t kToneDurationNs = 2000000000ULL;
constexpr size_t kFftSize = 262144;

struct Options {
	bool live = false;
	unsigned points = kDefaultPoints;
	unsigned repeats = 1;
	long double source_ppm = 0.0L;
	long double receiver_ppm = 0.0L;
	long double parent_hz = kNominalParentHz;
	double maximum_direct_hz = kMaximumDirectHz;
	std::vector<double> frequencies_hz;
	std::string output = "-";
};
struct Plan {
	double requested_hz;
	double fundamental_hz;
	unsigned harmonic;
	double planned_fundamental_hz;
	double planned_rf_hz;
	rp1_gpclk_tone tone;
};
struct Measurement {
	double raw_hz;
	double level_dbfs;
	double worst_spur_dbc;
	double median_noise_dbc;
	size_t samples;
};

[[noreturn]] void usage(const char *program, const std::string &error = {})
{
	if (!error.empty()) fprintf(stderr, "%s\n", error.c_str());
	fprintf(stderr, "usage: %s [--render-only|--live] [--points 2..101] "
		"[--repeats N] [--source-rate-ppm PPM] [--receiver-ppm PPM] "
		"[--parent-hz HZ] [--maximum-direct-hz HZ] [--frequency-hz HZ]... "
		"[--output PATH|-]\n", program);
	exit(error.empty() ? 0 : 2);
}
long double number(const char *text, const char *label)
{
	char *end = nullptr;
	const long double value = strtold(text, &end);
	if (!end || *end || !std::isfinite(value))
		throw std::runtime_error(std::string("invalid ") + label);
	return value;
}
unsigned whole(const char *text, const char *label)
{
	char *end = nullptr;
	const unsigned long value = strtoul(text, &end, 10);
	if (!end || *end || value > UINT32_MAX)
		throw std::runtime_error(std::string("invalid ") + label);
	return static_cast<unsigned>(value);
}
Options options(int argc, char **argv)
{
	Options out;
	for (int i = 1; i < argc; ++i) {
		const std::string arg = argv[i];
		auto next = [&](const char *label) {
			if (++i >= argc) usage(argv[0], std::string("missing ") + label);
			return argv[i];
		};
		if (arg == "--render-only") out.live = false;
		else if (arg == "--live") out.live = true;
		else if (arg == "--points") out.points = whole(next("points"), "points");
		else if (arg == "--repeats") out.repeats = whole(next("repeats"), "repeats");
		else if (arg == "--source-rate-ppm") out.source_ppm = number(next("source PPM"), "source PPM");
		else if (arg == "--receiver-ppm") out.receiver_ppm = number(next("receiver PPM"), "receiver PPM");
		else if (arg == "--parent-hz") out.parent_hz = number(next("parent frequency"), "parent frequency");
		else if (arg == "--maximum-direct-hz") out.maximum_direct_hz = static_cast<double>(number(next("maximum direct frequency"), "maximum direct frequency"));
		else if (arg == "--frequency-hz") out.frequencies_hz.push_back(static_cast<double>(number(next("frequency"), "frequency")));
		else if (arg == "--output") out.output = next("output");
		else if (arg == "--help") usage(argv[0]);
		else usage(argv[0], "unknown option: " + arg);
	}
	if (out.points < 2 || out.points > 101) usage(argv[0], "points must be 2..101");
	if (!out.repeats || out.repeats > 100) usage(argv[0], "repeats must be 1..100");
	if (fabsl(out.source_ppm) > 200 || fabsl(out.receiver_ppm) > 200)
		usage(argv[0], "PPM values must be within +/-200");
	if (out.live && out.parent_hz != kNominalParentHz)
		usage(argv[0], "live output requires the nominal 200 MHz parent; "
			"use --source-rate-ppm for source calibration");
	if (out.parent_hz <= 0 || out.parent_hz > 1000000000.0L ||
	    out.maximum_direct_hz <= 0 || out.maximum_direct_hz > out.parent_hz ||
	    out.maximum_direct_hz > kMaximumDirectHz)
		usage(argv[0], "parent/direct frequencies are inconsistent");
	for (double frequency : out.frequencies_hz)
		if (frequency < kMinimumHz || frequency > kMaximumHz)
			usage(argv[0], "frequency must be within 135700..148000000 Hz");
	return out;
}
void set_header(rp1_gpclk_uapi_header &header, size_t size)
{
	header.size = static_cast<uint16_t>(size);
}
Plan plan(double requested, long double parent, double maximum_direct)
{
	Plan out{};
	out.requested_hz = requested;
	out.harmonic = requested > maximum_direct ? 3U : 1U;
	out.fundamental_hz = requested / out.harmonic;
	const long double ideal = parent * 65536.0L / out.fundamental_hz;
	if (ideal < 65536.0L || ideal > 4294967295.0L)
		throw std::runtime_error("divider outside GPCLK0 Q16 field");
	uint64_t lower = static_cast<uint64_t>(floorl(ideal));
	if (lower == 0xffffffffULL)
		throw std::runtime_error("divider outside GPCLK0 Q16 field");
	if ((lower >> 16) != ((lower + 1) >> 16)) {
		const uint64_t nearest = static_cast<uint64_t>(llroundl(ideal));

		if (nearest == 0 || nearest >= 0xffffffffULL)
			throw std::runtime_error("integer crossing has no bounded divider pair");
		if ((nearest & 0xffffU) == 0xffffU)
			lower = nearest - 1;
		else
			lower = nearest;
	}
	const long double low_hz = parent * 65536.0L / lower;
	const long double high_div_hz = parent * 65536.0L / (lower + 1);
	const long double ratio = (out.fundamental_hz - high_div_hz) /
		(low_hz - high_div_hz);
	out.tone.lower_divider_q16 = lower;
	out.tone.upper_divider_q16 = lower + 1;
	out.tone.lower_count = static_cast<uint32_t>(llroundl(
		std::clamp(ratio, 0.0L, 1.0L) * kDitherPeriod));
	if (!out.tone.lower_count) out.tone.lower_count = 1;
	if (out.tone.lower_count >= kDitherPeriod) out.tone.lower_count = kDitherPeriod - 1;
	out.tone.upper_count = kDitherPeriod - out.tone.lower_count;
	out.planned_fundamental_hz = static_cast<double>((low_hz * out.tone.lower_count +
		high_div_hz * out.tone.upper_count) / kDitherPeriod);
	out.planned_rf_hz = out.planned_fundamental_hz * out.harmonic;
	return out;
}
void checked_ioctl(int fd, unsigned long command, void *value, const char *name)
{
	if (ioctl(fd, command, value))
		throw std::runtime_error(std::string(name) + ": " + strerror(errno));
}
class Endpoint {
public:
	Endpoint() : fd_(open("/dev/rp1-gpclk", O_RDONLY | O_CLOEXEC))
	{
		if (fd_ < 0) throw std::runtime_error(std::string("open: ") + strerror(errno));
	}
	~Endpoint() { if (fd_ >= 0) close(fd_); }
	void transmit(const rp1_gpclk_tone &tone)
	{
		rp1_gpclk_query query{};
		rp1_gpclk_acquire acquire{};
		rp1_gpclk_submit_events submit{};
		rp1_gpclk_event event{};
		rp1_gpclk_state_request state{};
		rp1_gpclk_release release{};
		set_header(query.header, sizeof(query));
		checked_ioctl(fd_, RP1_GPCLK_IOC_QUERY, &query, "QUERY");
		if (query.route != RP1_GPCLK_ROUTE_GPIO20 || !query.build_id[0] ||
		    !query.compatibility_id[0])
			throw std::runtime_error("GPIO20 development identity unavailable");
		set_header(acquire.header, sizeof(acquire));
		acquire.expected_route = RP1_GPCLK_ROUTE_GPIO20;
		acquire.required_capabilities = RP1_GPCLK_CAP_SUBMIT_EVENTS |
			RP1_GPCLK_CAP_BOUNDED_DMA_CHUNKS;
		checked_ioctl(fd_, RP1_GPCLK_IOC_ACQUIRE, &acquire, "ACQUIRE");
		set_header(submit.header, sizeof(submit));
		submit.lease_id = acquire.lease_id;
		event.duration_ns = kToneDurationNs;
		event.flags = RP1_GPCLK_EVENT_F_OUTPUT_ENABLED;
		submit.tones_ptr = reinterpret_cast<uintptr_t>(&tone);
		submit.events_ptr = reinterpret_cast<uintptr_t>(&event);
		submit.fractional_bits = RP1_GPCLK_FRACTIONAL_BITS;
		submit.tick_divider = RP1_GPCLK_TICK_DIVIDER;
		submit.tone_count = 1;
		submit.event_count = 1;
		submit.drive_ma = RP1_GPCLK_DRIVE_MA_2;
		submit.total_duration_ns = kToneDurationNs;
		checked_ioctl(fd_, RP1_GPCLK_IOC_SUBMIT_EVENTS, &submit, "SUBMIT_EVENTS");
		for (;;) {
			std::this_thread::sleep_for(std::chrono::milliseconds(10));
			state = {};
			set_header(state.header, sizeof(state));
			state.lease_id = acquire.lease_id;
			state.generation = submit.generation;
			checked_ioctl(fd_, RP1_GPCLK_IOC_GET_STATE, &state, "GET_STATE");
			if (state.state == RP1_GPCLK_STATE_COMPLETE || state.state == RP1_GPCLK_STATE_FAILED) break;
		}
		if (state.state != RP1_GPCLK_STATE_COMPLETE || state.cleanup_fault ||
		    state.terminal_reason != RP1_GPCLK_REASON_COMPLETE)
			throw std::runtime_error("finite tone did not complete cleanly");
		set_header(release.header, sizeof(release));
		release.lease_id = acquire.lease_id;
		release.generation = submit.generation;
		for (unsigned attempt = 0;; ++attempt) {
			if (!ioctl(fd_, RP1_GPCLK_IOC_RELEASE, &release))
				break;
			if (errno != EALREADY || attempt == 49)
				throw std::runtime_error(std::string("RELEASE: ") +
					strerror(errno));
			std::this_thread::sleep_for(std::chrono::milliseconds(10));
		}
	}
private: int fd_;
};
void fft(std::vector<std::complex<double>> &v)
{
	for (size_t i = 1, j = 0; i < v.size(); ++i) {
		size_t bit = v.size() >> 1;
		for (; j & bit; bit >>= 1) j ^= bit;
		j ^= bit;
		if (i < j) std::swap(v[i], v[j]);
	}
	for (size_t len = 2; len <= v.size(); len <<= 1) {
		const auto step = std::polar(1.0, -2.0 * M_PI / len);
		for (size_t start = 0; start < v.size(); start += len) {
			std::complex<double> phase(1, 0);
			for (size_t off = 0; off < len / 2; ++off) {
				const auto even = v[start + off];
				const auto odd = v[start + off + len / 2] * phase;
				v[start + off] = even + odd;
				v[start + off + len / 2] = even - odd;
				phase *= step;
			}
		}
	}
}
Measurement capture(SoapySDR::Device *sdr, Endpoint &endpoint, const Plan &p)
{
	const double center = p.requested_hz > kTuneOffsetHz + kSampleRate / 2 ?
		p.requested_hz - kTuneOffsetHz : p.requested_hz + kTuneOffsetHz;
	const double expected = p.requested_hz - center;
	std::vector<std::complex<float>> buffer(16384);
	std::vector<std::complex<double>> samples;
	long double power = 0;
	size_t accepted = 0;
	std::exception_ptr tx_error;
	samples.reserve(kFftSize);
	sdr->setSampleRate(SOAPY_SDR_RX, 0, kSampleRate);
	sdr->setBandwidth(SOAPY_SDR_RX, 0, 200000);
	sdr->setFrequency(SOAPY_SDR_RX, 0, center);
	sdr->setGainMode(SOAPY_SDR_RX, 0, false);
	sdr->setGain(SOAPY_SDR_RX, 0, 0);
	auto *stream = sdr->setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32);
	sdr->activateStream(stream);
	std::thread tx([&]() { try { std::this_thread::sleep_for(std::chrono::milliseconds(250));
		endpoint.transmit(p.tone); } catch (...) { tx_error = std::current_exception(); } });
	try {
		const size_t discard = static_cast<size_t>(kSampleRate * .45);
		size_t received = 0;
		while (accepted < kFftSize) {
			void *buffers[] = {buffer.data()}; int flags = 0; long long time_ns = 0;
			const int count = sdr->readStream(stream, buffers, buffer.size(), flags, time_ns, 1000000);
			if (count < 0) throw std::runtime_error("SDR read failed: " + std::to_string(count));
			for (int i = 0; i < count && accepted < kFftSize; ++i, ++received) {
				if (received < discard) continue;
				const auto s = buffer[static_cast<size_t>(i)];
				samples.emplace_back(s.real(), s.imag()); power += std::norm(s); ++accepted;
			}
		}
		tx.join(); if (tx_error) std::rethrow_exception(tx_error);
	} catch (...) { if (tx.joinable()) tx.join(); sdr->deactivateStream(stream); sdr->closeStream(stream); throw; }
	sdr->deactivateStream(stream); sdr->closeStream(stream);
	for (size_t i = 0; i < samples.size(); ++i)
		samples[i] *= .5 - .5 * cos(2 * M_PI * i / (samples.size() - 1));
	fft(samples);
	const long expected_signed = lround(expected * kFftSize / kSampleRate);
	const size_t expected_bin = expected_signed >= 0 ? static_cast<size_t>(expected_signed) :
		static_cast<size_t>(static_cast<long>(kFftSize) + expected_signed);
	const size_t search = static_cast<size_t>(20000 * kFftSize / kSampleRate);
	size_t peak = expected_bin; long peak_offset = 0; double peak_power = 0;
	for (long off = -static_cast<long>(search); off <= static_cast<long>(search); ++off) {
		const size_t bin = (expected_bin + kFftSize + off) % kFftSize;
		if (std::norm(samples[bin]) > peak_power) {
			peak_power = std::norm(samples[bin]); peak = bin; peak_offset = off;
		}
	}
	const long signed_bin = peak <= kFftSize / 2 ? static_cast<long>(peak) : static_cast<long>(peak) - kFftSize;
	const double left = std::norm(samples[(peak + kFftSize - 1) % kFftSize]);
	const double mid = std::norm(samples[peak]); const double right = std::norm(samples[(peak + 1) % kFftSize]);
	const double denom = left - 2 * mid + right;
	const double frac = denom == 0 ? 0 : .5 * (left - right) / denom;
	std::vector<double> noise_bins;
	double worst_spur = 0;
	constexpr long kCarrierExclusionBins = 210;
	for (long off = -static_cast<long>(search); off <= static_cast<long>(search); ++off) {
		const long distance = std::abs(off - peak_offset);
		if (distance <= kCarrierExclusionBins) continue;
		const size_t bin = (expected_bin + kFftSize + off) % kFftSize;
		const double bin_power = std::norm(samples[bin]);
		noise_bins.push_back(bin_power);
		worst_spur = std::max(worst_spur, bin_power);
	}
	const size_t middle = noise_bins.size() / 2;
	std::nth_element(noise_bins.begin(), noise_bins.begin() + middle, noise_bins.end());
	const double median_noise = noise_bins[middle];
	return {center + (signed_bin + frac) * kSampleRate / kFftSize,
		10 * log10(static_cast<double>(power / accepted)),
		10 * log10(worst_spur / peak_power), 10 * log10(median_noise / peak_power),
		accepted};
}
void header(FILE *out)
{
	fprintf(out, "repeat,index,requested_rf_hz,fundamental_hz,harmonic,planned_fundamental_hz,planned_rf_hz,lower_divider_q16,upper_divider_q16,lower_count,upper_count,raw_sdr_hz,corrected_sdr_hz,error_hz,error_ppm,level_dbfs,worst_spur_dbc,median_noise_dbc,samples,status\n");
}
}
int main(int argc, char **argv)
{
	try {
		const Options o = options(argc, argv);
		const long double parent = o.parent_hz * (1 + o.source_ppm * 1e-6L);
		FILE *out = o.output == "-" ? stdout : fopen(o.output.c_str(), "w");
		if (!out) throw std::runtime_error("cannot open output");
		SoapySDR::Device *sdr = nullptr;
		if (o.live) { SoapySDR::Kwargs a; a["driver"] = "sdrplay"; a["serial"] = "2404058C60";
			sdr = SoapySDR::Device::make(a); if (!sdr) throw std::runtime_error("SDRplay unavailable"); }
		header(out);
		const unsigned point_count = o.frequencies_hz.empty() ? o.points : o.frequencies_hz.size();
		for (unsigned repeat = 1; repeat <= o.repeats; ++repeat) for (unsigned index = 0; index < point_count; ++index) {
			const double requested = !o.frequencies_hz.empty() ? o.frequencies_hz[index] :
				kMinimumHz + (kMaximumHz - kMinimumHz) * index / (o.points - 1);
			try {
				const Plan p = plan(requested, parent, o.maximum_direct_hz);
				if (!o.live) fprintf(out, "%u,%u,%.6f,%.6f,%u,%.9f,%.9f,%llu,%llu,%u,%u,,,,,,,,,planned\n", repeat, index, p.requested_hz, p.fundamental_hz, p.harmonic, p.planned_fundamental_hz, p.planned_rf_hz, static_cast<unsigned long long>(p.tone.lower_divider_q16), static_cast<unsigned long long>(p.tone.upper_divider_q16), p.tone.lower_count, p.tone.upper_count);
				else { Endpoint endpoint; const Measurement m = capture(sdr, endpoint, p); const double corrected = m.raw_hz / (1 + static_cast<double>(o.receiver_ppm) * 1e-6); const double error = corrected - requested;
					fprintf(out, "%u,%u,%.6f,%.6f,%u,%.9f,%.9f,%llu,%llu,%u,%u,%.9f,%.9f,%.9f,%.9f,%.2f,%.2f,%.2f,%zu,measured\n", repeat, index, p.requested_hz, p.fundamental_hz, p.harmonic, p.planned_fundamental_hz, p.planned_rf_hz, static_cast<unsigned long long>(p.tone.lower_divider_q16), static_cast<unsigned long long>(p.tone.upper_divider_q16), p.tone.lower_count, p.tone.upper_count, m.raw_hz, corrected, error, error * 1e6 / requested, m.level_dbfs, m.worst_spur_dbc, m.median_noise_dbc, m.samples); }
			} catch (const std::exception &e) { fprintf(out, "%u,%u,%.6f,,,,,,,,,,,,,,,,,,,rejected:%s\n", repeat, index, requested, e.what()); }
			fflush(out);
		}
		if (sdr) SoapySDR::Device::unmake(sdr);
		if (out != stdout && fclose(out)) throw std::runtime_error("cannot close output");
	} catch (const std::exception &e) { fprintf(stderr, "frequency sweep failed: %s\n", e.what()); return 1; }
	return 0;
}
